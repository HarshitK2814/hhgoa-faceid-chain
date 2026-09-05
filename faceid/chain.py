"""Blockchain connectivity: compile FaceRegistry.sol, deploy it (once), and
call anchor()/verify() against either a real Polygon Amoy testnet RPC or a
local in-process EVM (eth-tester) that needs no network access at all.

The local chain exists so the whole pipeline can be proven correct before
any faucet / RPC dependency is in the loop, per the build plan.
"""
from __future__ import annotations

import json
import os
import pathlib
from typing import Any, Optional
from urllib.parse import urlparse

import solcx
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

CONTRACTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "contracts"
OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "out"
SOLC_VERSION = "0.8.24"

AMOY_RPC_DEFAULT = "https://polygon-amoy-bor-rpc.publicnode.com"
AMOY_CHAIN_ID = 80002
AMOY_EXPLORER_TX = "https://amoy.polygonscan.com/tx/{}"
AMOY_EXPLORER_ADDR = "https://amoy.polygonscan.com/address/{}"


def _deployment_file(mode: str) -> pathlib.Path:
    # One cache file per chain mode -- "local" and "amoy" must never share a
    # cache file. A --chain local rehearsal run (which always force-redeploys,
    # see deploy_or_load) would otherwise silently overwrite the cached amoy
    # contract address, making the next --chain amoy run think it needs to
    # redeploy (real gas, and likely more than a low-balance wallet has) when
    # a perfectly good contract is already live on-chain.
    return OUT_DIR / f"deployment_{mode}.json"


def _ensure_solc() -> None:
    installed = [str(v) for v in solcx.get_installed_solc_versions()]
    if SOLC_VERSION not in installed:
        solcx.install_solc(SOLC_VERSION)


def compile_contract() -> dict[str, Any]:
    _ensure_solc()
    src_path = CONTRACTS_DIR / "FaceRegistry.sol"
    compiled = solcx.compile_files(
        [str(src_path)],
        output_values=["abi", "bin"],
        solc_version=SOLC_VERSION,
    )
    # solcx normalizes the source path in its output keys (may be relative,
    # forward-slashed, etc. depending on cwd/platform) -- match by suffix
    # instead of reconstructing the exact key.
    for key, value in compiled.items():
        if key.endswith("FaceRegistry.sol:FaceRegistry"):
            return value
    raise RuntimeError(f"FaceRegistry not found in solc output: {list(compiled.keys())}")


class Chain:
    """Wraps a web3.py connection + the FaceRegistry contract, for either
    'local' (eth-tester in-process EVM) or 'amoy' (Polygon Amoy testnet).
    """

    def __init__(self, mode: str):
        assert mode in ("local", "amoy"), mode
        self.mode = mode
        self.explorer_tx_fmt: Optional[str] = None
        self.explorer_addr_fmt: Optional[str] = None

        if mode == "local":
            from web3 import EthereumTesterProvider

            self.w3 = Web3(EthereumTesterProvider())
            self.account = self.w3.eth.accounts[0]
            self._private_key = None  # eth-tester signs local accounts itself
        else:
            rpc_url = os.environ.get("AMOY_RPC_URL", AMOY_RPC_DEFAULT)
            private_key = os.environ.get("PRIVATE_KEY")
            if not private_key:
                raise RuntimeError(
                    "PRIVATE_KEY not set in .env -- run scripts/new_wallet.py, "
                    "fund it from the Polygon Amoy faucet, then set PRIVATE_KEY."
                )
            self.w3 = Web3(Web3.HTTPProvider(rpc_url))
            self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            self._private_key = private_key
            acct = self.w3.eth.account.from_key(private_key)
            self.account = acct.address
            self.explorer_tx_fmt = AMOY_EXPLORER_TX
            self.explorer_addr_fmt = AMOY_EXPLORER_ADDR
            if not self.w3.is_connected():
                # Host only, never the full URL: provider RPC URLs commonly
                # embed an API key in the path (Alchemy/Infura), which would
                # otherwise be printed to the terminal.
                raise RuntimeError(
                    f"Could not connect to Amoy RPC at {urlparse(rpc_url).netloc}"
                )

        self.contract = None
        self.contract_address: Optional[str] = None

    # -- deployment -------------------------------------------------
    def deploy_or_load(self, force_new: bool = False) -> str:
        # eth-tester's EthereumTesterProvider is an in-process, in-memory
        # EVM: its state does not survive past this Python process, so a
        # cached address from a previous run would never have code on a
        # fresh 'local' instance. Always deploy fresh in that mode instead
        # of hitting a confusing "no code at address" error later.
        if self.mode == "local":
            force_new = True
        cached = self._load_cached_deployment()
        if not force_new and cached and cached.get("mode") == self.mode:
            addr = cached["address"]
            abi = cached["abi"]
            if self.mode == "amoy" and self.w3.eth.get_code(addr) == b"":
                pass  # cached address has no code on this network, redeploy below
            else:
                self.contract_address = addr
                self.contract = self.w3.eth.contract(address=addr, abi=abi)
                return addr

        compiled = compile_contract()
        abi = compiled["abi"]
        bytecode = compiled["bin"]
        Contract = self.w3.eth.contract(abi=abi, bytecode=bytecode)

        if self.mode == "local":
            tx_hash = Contract.constructor().transact({"from": self.account})
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        else:
            nonce = self.w3.eth.get_transaction_count(self.account)
            gas_estimate = Contract.constructor().estimate_gas({"from": self.account})
            tx = Contract.constructor().build_transaction(
                {
                    "from": self.account,
                    "nonce": nonce,
                    "chainId": AMOY_CHAIN_ID,
                    "gas": int(gas_estimate * 1.2),
                    "gasPrice": self.w3.eth.gas_price,
                }
            )
            signed = self.w3.eth.account.sign_transaction(tx, self._private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)

        address = receipt.contractAddress
        self.contract_address = address
        self.contract = self.w3.eth.contract(address=address, abi=abi)
        self._save_deployment(address, abi)
        return address

    def _load_cached_deployment(self) -> Optional[dict[str, Any]]:
        path = _deployment_file(self.mode)
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                return None
        return None

    def _save_deployment(self, address: str, abi: list) -> None:
        path = _deployment_file(self.mode)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"mode": self.mode, "address": address, "abi": abi}, indent=2)
        )

    # -- interaction --------------------------------------------------
    def anchor(self, record_hash: bytes, uri: str) -> dict[str, Any]:
        assert self.contract is not None, "call deploy_or_load() first"

        if self.mode == "local":
            tx_hash = self.contract.functions.anchor(record_hash, uri).transact(
                {"from": self.account}
            )
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        else:
            nonce = self.w3.eth.get_transaction_count(self.account)
            gas_estimate = self.contract.functions.anchor(record_hash, uri).estimate_gas(
                {"from": self.account}
            )
            tx = self.contract.functions.anchor(record_hash, uri).build_transaction(
                {
                    "from": self.account,
                    "nonce": nonce,
                    "chainId": AMOY_CHAIN_ID,
                    "gas": int(gas_estimate * 1.2),
                    "gasPrice": self.w3.eth.gas_price,
                }
            )
            signed = self.w3.eth.account.sign_transaction(tx, self._private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)

        return {
            "tx_hash": "0x" + receipt.transactionHash.hex().removeprefix("0x"),
            "block_number": receipt.blockNumber,
            "contract_address": self.contract_address,
            "status": receipt.status,
            "explorer_tx_url": self.explorer_tx_fmt.format(
                "0x" + receipt.transactionHash.hex().removeprefix("0x")
            )
            if self.explorer_tx_fmt
            else None,
            "explorer_addr_url": self.explorer_addr_fmt.format(self.contract_address)
            if self.explorer_addr_fmt
            else None,
        }

    def verify(self, record_hash: bytes) -> dict[str, Any]:
        assert self.contract is not None, "call deploy_or_load() first"
        exists, timestamp, submitter, uri = self.contract.functions.verify(record_hash).call()
        return {
            "exists": exists,
            "timestamp": timestamp,
            "submitter": submitter,
            "uri": uri,
        }
