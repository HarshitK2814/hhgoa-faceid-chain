// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title FaceRegistry
/// @notice Minimal tamper-evident anchor: stores a keccak256 hash of an
/// off-chain "match record" (face embedding hash + matched social post URL
/// + similarity score + timestamp) together with who submitted it and when.
/// Re-anchoring the same hash reverts, which is itself part of the
/// tamper-evidence story -- you cannot silently overwrite a prior record.
contract FaceRegistry {
    struct Record {
        uint64 timestamp;
        address submitter;
        string uri;
    }

    mapping(bytes32 => Record) public records;

    event Anchored(
        bytes32 indexed recordHash,
        address indexed submitter,
        uint64 timestamp,
        string uri
    );

    /// @notice Anchor a new record hash on-chain.
    /// @param recordHash keccak256 of the canonical JSON match record.
    /// @param uri The matched social media post URL (context for humans;
    ///        the hash is the actual tamper-evident commitment).
    function anchor(bytes32 recordHash, string calldata uri) external {
        require(records[recordHash].timestamp == 0, "already anchored");
        records[recordHash] = Record({
            timestamp: uint64(block.timestamp),
            submitter: msg.sender,
            uri: uri
        });
        emit Anchored(recordHash, msg.sender, uint64(block.timestamp), uri);
    }

    /// @notice Re-verify a record hash against the on-chain record.
    function verify(bytes32 recordHash)
        external
        view
        returns (bool exists, uint64 timestamp, address submitter, string memory uri)
    {
        Record storage r = records[recordHash];
        exists = r.timestamp != 0;
        timestamp = r.timestamp;
        submitter = r.submitter;
        uri = r.uri;
    }
}
