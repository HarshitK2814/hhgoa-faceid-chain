"""Generate a throwaway Amoy testnet wallet. NEVER use this for real funds.

Prints the address (to fund from the faucet) and the private key (to put
in .env as PRIVATE_KEY). Run once, fund the address, then leave the key in
.env for faceid/chain.py to use.
"""
from eth_account import Account


def main() -> None:
    Account.enable_unaudited_hdwallet_features()
    acct = Account.create()
    print("=== Throwaway Polygon Amoy testnet wallet ===")
    print(f"Address:     {acct.address}")
    print(f"Private key: {acct.key.hex()}")
    print()
    print("1. Fund this address at https://faucet.polygon.technology (select Amoy, ~0.1 POL)")
    print("2. Put the private key in .env as PRIVATE_KEY=<key above>")
    print("   NEVER reuse this key for a real wallet.")


if __name__ == "__main__":
    main()
