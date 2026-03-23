// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

contract ColdChainMonitorV3 {
    // ============ Access Control ============

    address public owner;
    mapping(address => bool) private authorizedUploaders;

    error NotOwner();
    error NotAuthorized();
    error InvalidAddress();
    error AlreadyAuthorized();
    error AlreadyUnauthorized();
    error CannotRemoveOwner();

    modifier onlyOwner() {
        if (msg.sender != owner) {
            revert NotOwner();
        }
        _;
    }

    modifier onlyAuthorized() {
        if (!authorizedUploaders[msg.sender]) {
            revert NotAuthorized();
        }
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
        uint64 timestamp;
        address uploader;
        bool exists;
        bytes32 dataHashDigest;
    }

    mapping(bytes32 => OrderHashRecord) private orderHashes;
    mapping(bytes32 => string) private orderHashText;

    event OrderHashStored(string orderId, string dataHash, uint256 timestamp);
    event OrderHashDigestStored(
        string orderId,
        bytes32 dataHashDigest,
        uint256 timestamp
    );

    // ============ Driver Anchors (Low-Gas Identity Proof) ============

    struct DriverAnchor {
        bytes32 driverRefHash;
        bytes32 idCommit;
        bytes32 profileHash;
        address uploader;
        uint64 updatedAt;
        bool exists;
    }

    mapping(bytes32 => DriverAnchor) private driverAnchors;

    event DriverAnchorUpserted(
        string orderId,
        bytes32 driverRefHash,
        bytes32 idCommit,
        bytes32 profileHash,
        uint256 updatedAt,
        address uploader
    );

    // ============ Anomaly Records ============

    struct AnomalyRecord {
        uint64 startTime;
        uint64 endTime;
        int256 triggerValue;
        int256 peakValue;
        address uploader;
        bytes32 orderKey;
        bytes32 anomalyTypeKey;
        bytes32 encryptedInfoHash;
        bool closed;
        bool exists;
        bool hasInlineEncryptedInfo;
    }

    uint256 public anomalyCount;
    mapping(uint256 => AnomalyRecord) private anomalies;
    mapping(bytes32 => uint256[]) private orderAnomalyIds;
    mapping(bytes32 => string) private orderIdDict;
    mapping(bytes32 => string) private anomalyTypeDict;
    mapping(uint256 => string) private anomalyEncryptedInfo;

    event AnomalyStarted(
        uint256 indexed anomalyId,
        string orderId,
        string anomalyType,
        int256 triggerValue,
        uint256 startTime
    );

    event AnomalyStartedLite(
        uint256 indexed anomalyId,
        string orderId,
        string anomalyType,
        int256 triggerValue,
        uint256 startTime,
        bytes32 encryptedInfoHash
    );

    event AnomalyClosed(uint256 indexed anomalyId, uint256 endTime, int256 peakValue);

    error OrderIdRequired();
    error DataHashRequired();
    error DataHashDigestRequired();
    error OrderHashAlreadyExists();
    error OrderHashNotFound();
    error AnomalyTypeRequired();
    error InvalidStartTime();
    error EncryptedInfoRequired();
    error EncryptedInfoHashRequired();
    error AnomalyNotFound();
    error AnomalyAlreadyClosed();
    error EndTimeMustBeAfterStartTime();
    error TimeOverflow();
    error DriverRefHashRequired();
    error IdCommitRequired();
    error ProfileHashRequired();

    constructor() {
        owner = msg.sender;
        authorizedUploaders[msg.sender] = true;
        emit AuthorizedAdded(msg.sender);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) {
            revert InvalidAddress();
        }

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
        if (account == address(0)) {
            revert InvalidAddress();
        }
        if (authorizedUploaders[account]) {
            revert AlreadyAuthorized();
        }
        authorizedUploaders[account] = true;
        emit AuthorizedAdded(account);
    }

    function removeAuthorized(address account) external onlyOwner {
        if (account == address(0)) {
            revert InvalidAddress();
        }
        if (!authorizedUploaders[account]) {
            revert AlreadyUnauthorized();
        }
        if (account == owner) {
            revert CannotRemoveOwner();
        }
        authorizedUploaders[account] = false;
        emit AuthorizedRemoved(account);
    }

    function isAuthorized(address account) external view returns (bool) {
        return authorizedUploaders[account];
    }

    // ============ Order Hash (Legacy Compatible) ============

    function storeOrderHash(
        string calldata orderId,
        string calldata dataHash
    ) external onlyAuthorized {
        if (bytes(orderId).length == 0) {
            revert OrderIdRequired();
        }
        if (bytes(dataHash).length == 0) {
            revert DataHashRequired();
        }

        bytes32 orderKey = _orderKey(orderId);
        if (orderHashes[orderKey].exists) {
            revert OrderHashAlreadyExists();
        }

        orderHashes[orderKey] = OrderHashRecord({
            timestamp: _asUint64(block.timestamp),
            uploader: msg.sender,
            exists: true,
            dataHashDigest: keccak256(bytes(dataHash))
        });
        orderHashText[orderKey] = dataHash;

        emit OrderHashStored(orderId, dataHash, block.timestamp);
    }

    function getOrderHash(
        string calldata orderId
    ) external view returns (string memory, string memory, uint256, address) {
        bytes32 orderKey = _orderKey(orderId);
        OrderHashRecord memory record = orderHashes[orderKey];
        require(record.exists, "Order hash not found");
        string memory dataHash = orderHashText[orderKey];
        if (bytes(dataHash).length == 0) {
            dataHash = _bytes32ToHex(record.dataHashDigest);
        }
        return (orderId, dataHash, uint256(record.timestamp), record.uploader);
    }

    function verifyOrderHash(
        string calldata orderId,
        string calldata dataHash
    ) external view returns (bool) {
        bytes32 orderKey = _orderKey(orderId);
        OrderHashRecord memory record = orderHashes[orderKey];
        if (!record.exists) {
            return false;
        }
        return record.dataHashDigest == keccak256(bytes(dataHash));
    }

    // ============ Order Hash (Low-Gas Path) ============

    function storeOrderHashDigest(
        string calldata orderId,
        bytes32 dataHashDigest
    ) external onlyAuthorized {
        if (bytes(orderId).length == 0) {
            revert OrderIdRequired();
        }
        if (dataHashDigest == bytes32(0)) {
            revert DataHashDigestRequired();
        }

        bytes32 orderKey = _orderKey(orderId);
        if (orderHashes[orderKey].exists) {
            revert OrderHashAlreadyExists();
        }

        orderHashes[orderKey] = OrderHashRecord({
            timestamp: _asUint64(block.timestamp),
            uploader: msg.sender,
            exists: true,
            dataHashDigest: dataHashDigest
        });

        emit OrderHashDigestStored(orderId, dataHashDigest, block.timestamp);
    }

    function getOrderHashDigest(
        string calldata orderId
    ) external view returns (bytes32 dataHashDigest, uint256 timestamp, address uploader) {
        bytes32 orderKey = _orderKey(orderId);
        OrderHashRecord memory record = orderHashes[orderKey];
        require(record.exists, "Order hash not found");
        return (record.dataHashDigest, uint256(record.timestamp), record.uploader);
    }

    function verifyOrderHashDigest(
        string calldata orderId,
        bytes32 dataHashDigest
    ) external view returns (bool) {
        bytes32 orderKey = _orderKey(orderId);
        OrderHashRecord memory record = orderHashes[orderKey];
        if (!record.exists) {
            return false;
        }
        return record.dataHashDigest == dataHashDigest;
    }

    function upsertDriverAnchor(
        string calldata orderId,
        bytes32 driverRefHash,
        bytes32 idCommit,
        bytes32 profileHash
    ) external onlyAuthorized {
        if (bytes(orderId).length == 0) {
            revert OrderIdRequired();
        }

        bytes32 orderKey = _orderKey(orderId);
        _upsertDriverAnchorInternal(
            orderId,
            orderKey,
            driverRefHash,
            idCommit,
            profileHash
        );
    }

    function getDriverAnchor(
        string calldata orderId
    )
        external
        view
        returns (
            bytes32 driverRefHash,
            bytes32 idCommit,
            bytes32 profileHash,
            uint256 updatedAt,
            address uploader,
            bool exists
        )
    {
        DriverAnchor memory anchor = driverAnchors[_orderKey(orderId)];
        return (
            anchor.driverRefHash,
            anchor.idCommit,
            anchor.profileHash,
            uint256(anchor.updatedAt),
            anchor.uploader,
            anchor.exists
        );
    }

    // ============ Anomaly (Legacy Compatible) ============

    function startAnomaly(
        string calldata orderId,
        string calldata anomalyType,
        int256 triggerValue,
        uint256 startTime,
        string calldata encryptedInfo
    ) external onlyAuthorized returns (uint256) {
        if (bytes(orderId).length == 0) {
            revert OrderIdRequired();
        }
        if (bytes(anomalyType).length == 0) {
            revert AnomalyTypeRequired();
        }
        if (startTime == 0) {
            revert InvalidStartTime();
        }
        if (bytes(encryptedInfo).length == 0) {
            revert EncryptedInfoRequired();
        }

        bytes32 encryptedInfoHash = keccak256(bytes(encryptedInfo));
        return
            _startAnomalyInternal(
                orderId,
                anomalyType,
                triggerValue,
                startTime,
                encryptedInfoHash,
                true,
                encryptedInfo
            );
    }

    // ============ Anomaly (Low-Gas Path) ============

    function startAnomalyLite(
        string calldata orderId,
        string calldata anomalyType,
        int256 triggerValue,
        uint256 startTime,
        bytes32 encryptedInfoHash
    ) external onlyAuthorized returns (uint256) {
        if (bytes(orderId).length == 0) {
            revert OrderIdRequired();
        }
        if (bytes(anomalyType).length == 0) {
            revert AnomalyTypeRequired();
        }
        if (startTime == 0) {
            revert InvalidStartTime();
        }
        if (encryptedInfoHash == bytes32(0)) {
            revert EncryptedInfoHashRequired();
        }

        uint256 anomalyId = _startAnomalyInternal(
            orderId,
            anomalyType,
            triggerValue,
            startTime,
            encryptedInfoHash,
            false,
            ""
        );
        emit AnomalyStartedLite(
            anomalyId,
            orderId,
            anomalyType,
            triggerValue,
            startTime,
            encryptedInfoHash
        );
        return anomalyId;
    }

    function startAnomalyLiteWithAnchor(
        string calldata orderId,
        string calldata anomalyType,
        int256 triggerValue,
        uint256 startTime,
        bytes32 encryptedInfoHash,
        bytes32 driverRefHash,
        bytes32 idCommit,
        bytes32 profileHash
    ) external onlyAuthorized returns (uint256) {
        if (bytes(orderId).length == 0) {
            revert OrderIdRequired();
        }
        if (bytes(anomalyType).length == 0) {
            revert AnomalyTypeRequired();
        }
        if (startTime == 0) {
            revert InvalidStartTime();
        }
        if (encryptedInfoHash == bytes32(0)) {
            revert EncryptedInfoHashRequired();
        }

        bytes32 orderKey = _orderKey(orderId);
        _upsertDriverAnchorInternal(
            orderId,
            orderKey,
            driverRefHash,
            idCommit,
            profileHash
        );

        uint256 anomalyId = _startAnomalyInternal(
            orderId,
            anomalyType,
            triggerValue,
            startTime,
            encryptedInfoHash,
            false,
            ""
        );
        emit AnomalyStartedLite(
            anomalyId,
            orderId,
            anomalyType,
            triggerValue,
            startTime,
            encryptedInfoHash
        );
        return anomalyId;
    }

    function closeAnomaly(
        uint256 anomalyId,
        uint256 endTime,
        int256 peakValue
    ) external onlyAuthorized {
        AnomalyRecord storage record = anomalies[anomalyId];
        if (!record.exists) {
            revert AnomalyNotFound();
        }
        if (record.closed) {
            revert AnomalyAlreadyClosed();
        }

        uint64 endTime64 = _asUint64(endTime);
        if (endTime64 <= record.startTime) {
            revert EndTimeMustBeAfterStartTime();
        }

        record.endTime = endTime64;
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
        AnomalyRecord storage record = anomalies[anomalyId];
        require(record.exists, "Anomaly not found");

        string memory orderIdValue = orderIdDict[record.orderKey];
        string memory anomalyTypeValue = anomalyTypeDict[record.anomalyTypeKey];
        string memory encryptedInfoValue = "";
        if (record.hasInlineEncryptedInfo) {
            encryptedInfoValue = anomalyEncryptedInfo[anomalyId];
        }

        return (
            orderIdValue,
            anomalyTypeValue,
            record.triggerValue,
            uint256(record.startTime),
            uint256(record.endTime),
            record.peakValue,
            record.closed,
            encryptedInfoValue,
            record.uploader
        );
    }

    function getAnomalyMeta(
        uint256 anomalyId
    ) external view returns (bytes32 encryptedInfoHash, bool hasInlineEncryptedInfo) {
        AnomalyRecord memory record = anomalies[anomalyId];
        require(record.exists, "Anomaly not found");
        return (record.encryptedInfoHash, record.hasInlineEncryptedInfo);
    }

    function getAnomaliesByOrder(
        string calldata orderId
    ) external view returns (uint256[] memory) {
        return orderAnomalyIds[_orderKey(orderId)];
    }

    function _startAnomalyInternal(
        string calldata orderId,
        string calldata anomalyType,
        int256 triggerValue,
        uint256 startTime,
        bytes32 encryptedInfoHash,
        bool hasInlineEncryptedInfo,
        string memory encryptedInfo
    ) private returns (uint256) {
        bytes32 orderKey = _orderKey(orderId);
        bytes32 anomalyTypeKey = _anomalyTypeKey(anomalyType);
        _rememberText(orderIdDict, orderKey, orderId);
        _rememberText(anomalyTypeDict, anomalyTypeKey, anomalyType);

        anomalyCount += 1;
        uint256 anomalyId = anomalyCount;

        anomalies[anomalyId] = AnomalyRecord({
            startTime: _asUint64(startTime),
            endTime: 0,
            triggerValue: triggerValue,
            peakValue: triggerValue,
            uploader: msg.sender,
            orderKey: orderKey,
            anomalyTypeKey: anomalyTypeKey,
            encryptedInfoHash: encryptedInfoHash,
            closed: false,
            exists: true,
            hasInlineEncryptedInfo: hasInlineEncryptedInfo
        });

        if (hasInlineEncryptedInfo) {
            anomalyEncryptedInfo[anomalyId] = encryptedInfo;
        }
        orderAnomalyIds[orderKey].push(anomalyId);

        emit AnomalyStarted(
            anomalyId,
            orderId,
            anomalyType,
            triggerValue,
            startTime
        );
        return anomalyId;
    }

    function _upsertDriverAnchorInternal(
        string calldata orderId,
        bytes32 orderKey,
        bytes32 driverRefHash,
        bytes32 idCommit,
        bytes32 profileHash
    ) private {
        if (driverRefHash == bytes32(0)) {
            revert DriverRefHashRequired();
        }
        if (idCommit == bytes32(0)) {
            revert IdCommitRequired();
        }
        if (profileHash == bytes32(0)) {
            revert ProfileHashRequired();
        }

        _rememberText(orderIdDict, orderKey, orderId);
        DriverAnchor storage current = driverAnchors[orderKey];
        if (
            current.exists &&
            current.driverRefHash == driverRefHash &&
            current.idCommit == idCommit &&
            current.profileHash == profileHash
        ) {
            return;
        }

        uint64 updatedAt = _asUint64(block.timestamp);
        driverAnchors[orderKey] = DriverAnchor({
            driverRefHash: driverRefHash,
            idCommit: idCommit,
            profileHash: profileHash,
            uploader: msg.sender,
            updatedAt: updatedAt,
            exists: true
        });
        emit DriverAnchorUpserted(
            orderId,
            driverRefHash,
            idCommit,
            profileHash,
            uint256(updatedAt),
            msg.sender
        );
    }

    function _rememberText(
        mapping(bytes32 => string) storage dict,
        bytes32 key,
        string calldata value
    ) private {
        if (bytes(dict[key]).length == 0) {
            dict[key] = value;
        }
    }

    function _orderKey(string calldata orderId) private pure returns (bytes32) {
        return keccak256(bytes(orderId));
    }

    function _anomalyTypeKey(
        string calldata anomalyType
    ) private pure returns (bytes32) {
        return keccak256(bytes(anomalyType));
    }

    function _asUint64(uint256 value) private pure returns (uint64) {
        if (value > type(uint64).max) {
            revert TimeOverflow();
        }
        return uint64(value);
    }

    function _bytes32ToHex(bytes32 value) private pure returns (string memory) {
        bytes memory alphabet = "0123456789abcdef";
        bytes memory out = new bytes(66);
        out[0] = "0";
        out[1] = "x";
        for (uint256 i = 0; i < 32; i++) {
            uint8 b = uint8(value[i]);
            out[2 + i * 2] = alphabet[b >> 4];
            out[3 + i * 2] = alphabet[b & 0x0f];
        }
        return string(out);
    }
}
