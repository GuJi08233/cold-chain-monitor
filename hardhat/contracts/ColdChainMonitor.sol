// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

contract ColdChainMonitor {
    // ============ Access Control ============

    address public owner;
    mapping(address => bool) private authorizedUploaders;

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    modifier onlyAuthorized() {
        require(authorizedUploaders[msg.sender], "Not authorized");
        _;
    }

    event OwnershipTransferred(
        address indexed previousOwner,
        address indexed newOwner
    );
    event AuthorizedAdded(address indexed account);
    event AuthorizedRemoved(address indexed account);

    // ============ Order Hash Records ============

    struct OrderHashRecord {
        string orderId;
        string dataHash;
        uint256 timestamp;
        address uploader;
        bool exists;
    }

    mapping(string => OrderHashRecord) private orderHashes;

    event OrderHashStored(string orderId, string dataHash, uint256 timestamp);

    // ============ Anomaly Records ============

    struct AnomalyRecord {
        string orderId;
        string anomalyType;
        int256 triggerValue;
        uint256 startTime;
        uint256 endTime;
        int256 peakValue;
        bool closed;
        string encryptedInfo;
        address uploader;
        bool exists;
    }

    uint256 public anomalyCount;
    mapping(uint256 => AnomalyRecord) private anomalies;
    mapping(string => uint256[]) private orderAnomalyIds;

    event AnomalyStarted(
        uint256 indexed anomalyId,
        string orderId,
        string anomalyType,
        int256 triggerValue,
        uint256 startTime
    );

    event AnomalyClosed(uint256 indexed anomalyId, uint256 endTime, int256 peakValue);

    constructor() {
        owner = msg.sender;
        authorizedUploaders[msg.sender] = true;
        emit AuthorizedAdded(msg.sender);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "Invalid address");

        address previousOwner = owner;
        owner = newOwner;

        // Keep a safe default after ownership rotation.
        authorizedUploaders[newOwner] = true;
        authorizedUploaders[previousOwner] = false;

        emit OwnershipTransferred(previousOwner, newOwner);
        emit AuthorizedAdded(newOwner);
        emit AuthorizedRemoved(previousOwner);
    }

    function addAuthorized(address account) external onlyOwner {
        require(account != address(0), "Invalid address");
        require(!authorizedUploaders[account], "Already authorized");
        authorizedUploaders[account] = true;
        emit AuthorizedAdded(account);
    }

    function removeAuthorized(address account) external onlyOwner {
        require(account != address(0), "Invalid address");
        require(authorizedUploaders[account], "Already unauthorized");
        require(account != owner, "Cannot remove owner");
        authorizedUploaders[account] = false;
        emit AuthorizedRemoved(account);
    }

    function isAuthorized(address account) external view returns (bool) {
        return authorizedUploaders[account];
    }

    function storeOrderHash(
        string calldata orderId,
        string calldata dataHash
    ) external onlyAuthorized {
        require(bytes(orderId).length > 0, "Order ID required");
        require(bytes(dataHash).length > 0, "Data hash required");
        require(!orderHashes[orderId].exists, "Order hash already exists");

        orderHashes[orderId] = OrderHashRecord({
            orderId: orderId,
            dataHash: dataHash,
            timestamp: block.timestamp,
            uploader: msg.sender,
            exists: true
        });

        emit OrderHashStored(orderId, dataHash, block.timestamp);
    }

    function getOrderHash(
        string calldata orderId
    ) external view returns (string memory, string memory, uint256, address) {
        OrderHashRecord memory record = orderHashes[orderId];
        require(record.exists, "Order hash not found");
        return (record.orderId, record.dataHash, record.timestamp, record.uploader);
    }

    function verifyOrderHash(
        string calldata orderId,
        string calldata dataHash
    ) external view returns (bool) {
        OrderHashRecord memory record = orderHashes[orderId];
        if (!record.exists) {
            return false;
        }
        return keccak256(bytes(record.dataHash)) == keccak256(bytes(dataHash));
    }

    function startAnomaly(
        string calldata orderId,
        string calldata anomalyType,
        int256 triggerValue,
        uint256 startTime,
        string calldata encryptedInfo
    ) external onlyAuthorized returns (uint256) {
        require(bytes(orderId).length > 0, "Order ID required");
        require(bytes(anomalyType).length > 0, "Anomaly type required");
        require(startTime > 0, "Invalid start time");
        require(bytes(encryptedInfo).length > 0, "Encrypted info required");

        anomalyCount++;
        uint256 anomalyId = anomalyCount;

        anomalies[anomalyId] = AnomalyRecord({
            orderId: orderId,
            anomalyType: anomalyType,
            triggerValue: triggerValue,
            startTime: startTime,
            endTime: 0,
            peakValue: triggerValue,
            closed: false,
            encryptedInfo: encryptedInfo,
            uploader: msg.sender,
            exists: true
        });

        orderAnomalyIds[orderId].push(anomalyId);

        emit AnomalyStarted(anomalyId, orderId, anomalyType, triggerValue, startTime);
        return anomalyId;
    }

    function closeAnomaly(
        uint256 anomalyId,
        uint256 endTime,
        int256 peakValue
    ) external onlyAuthorized {
        AnomalyRecord storage record = anomalies[anomalyId];
        require(record.exists, "Anomaly not found");
        require(!record.closed, "Anomaly already closed");
        require(endTime > record.startTime, "End time must be after start time");

        record.endTime = endTime;
        record.peakValue = peakValue;
        record.closed = true;

        emit AnomalyClosed(anomalyId, endTime, peakValue);
    }

    function getAnomaly(
        uint256 anomalyId
    )
        external
        view
        returns (
            string memory orderId,
            string memory anomalyType,
            int256 triggerValue,
            uint256 startTime,
            uint256 endTime,
            int256 peakValue,
            bool closed,
            string memory encryptedInfo,
            address uploader
        )
    {
        AnomalyRecord memory record = anomalies[anomalyId];
        require(record.exists, "Anomaly not found");
        return (
            record.orderId,
            record.anomalyType,
            record.triggerValue,
            record.startTime,
            record.endTime,
            record.peakValue,
            record.closed,
            record.encryptedInfo,
            record.uploader
        );
    }

    function getAnomaliesByOrder(
        string calldata orderId
    ) external view returns (uint256[] memory) {
        return orderAnomalyIds[orderId];
    }
}
