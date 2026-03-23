import { anyValue } from "@nomicfoundation/hardhat-chai-matchers/withArgs";
import { loadFixture, time } from "@nomicfoundation/hardhat-toolbox/network-helpers";
import { expect } from "chai";
import hre from "hardhat";

describe("ColdChainMonitor", function () {
  async function deployFixture() {
    const [owner, uploader, other] = await hre.ethers.getSigners();
    const Factory = await hre.ethers.getContractFactory("ColdChainMonitor");
    const contract = await Factory.deploy();
    return { contract, owner, uploader, other };
  }

  describe("Deployment", function () {
    it("should set deployer as owner and authorized uploader", async function () {
      const { contract, owner } = await loadFixture(deployFixture);

      expect(await contract.owner()).to.equal(owner.address);
      expect(await contract.isAuthorized(owner.address)).to.equal(true);
      expect(await contract.anomalyCount()).to.equal(0n);
    });
  });

  describe("Access control", function () {
    it("should only allow owner to manage authorized uploaders", async function () {
      const { contract, uploader, other } = await loadFixture(deployFixture);

      await expect(contract.connect(other).addAuthorized(uploader.address)).to.be.revertedWith(
        "Not owner",
      );
      await expect(contract.addAuthorized(uploader.address))
        .to.emit(contract, "AuthorizedAdded")
        .withArgs(uploader.address);
      expect(await contract.isAuthorized(uploader.address)).to.equal(true);

      await expect(contract.connect(other).removeAuthorized(uploader.address)).to.be.revertedWith(
        "Not owner",
      );
      await expect(contract.removeAuthorized(uploader.address))
        .to.emit(contract, "AuthorizedRemoved")
        .withArgs(uploader.address);
      expect(await contract.isAuthorized(uploader.address)).to.equal(false);
    });

    it("should not allow removing current owner from authorized list", async function () {
      const { contract, owner } = await loadFixture(deployFixture);
      await expect(contract.removeAuthorized(owner.address)).to.be.revertedWith(
        "Cannot remove owner",
      );
    });

    it("should rotate ownership and uploader permission safely", async function () {
      const { contract, owner, uploader } = await loadFixture(deployFixture);

      await expect(contract.transferOwnership(uploader.address))
        .to.emit(contract, "OwnershipTransferred")
        .withArgs(owner.address, uploader.address);

      expect(await contract.owner()).to.equal(uploader.address);
      expect(await contract.isAuthorized(uploader.address)).to.equal(true);
      expect(await contract.isAuthorized(owner.address)).to.equal(false);
    });
  });

  describe("Order hash records", function () {
    it("should store and query order hash once", async function () {
      const { contract, owner } = await loadFixture(deployFixture);
      const orderId = "ORD20260213001_080000";
      const dataHash = "sha256:abc123";

      await expect(contract.storeOrderHash(orderId, dataHash))
        .to.emit(contract, "OrderHashStored")
        .withArgs(orderId, dataHash, anyValue);

      const [savedOrderId, savedHash, timestamp, uploader] = await contract.getOrderHash(orderId);
      expect(savedOrderId).to.equal(orderId);
      expect(savedHash).to.equal(dataHash);
      expect(timestamp).to.be.greaterThan(0n);
      expect(uploader).to.equal(owner.address);

      await expect(contract.storeOrderHash(orderId, dataHash)).to.be.revertedWith(
        "Order hash already exists",
      );
    });

    it("should enforce uploader authorization for storing hash", async function () {
      const { contract, other } = await loadFixture(deployFixture);
      await expect(
        contract.connect(other).storeOrderHash("ORD20260213002_080000", "sha256:def456"),
      ).to.be.revertedWith("Not authorized");
    });

    it("should verify hash correctly", async function () {
      const { contract } = await loadFixture(deployFixture);
      const orderId = "ORD20260213003_080000";
      await contract.storeOrderHash(orderId, "sha256:hash-value");

      expect(await contract.verifyOrderHash(orderId, "sha256:hash-value")).to.equal(true);
      expect(await contract.verifyOrderHash(orderId, "sha256:another-value")).to.equal(false);
      expect(await contract.verifyOrderHash("NOT_EXIST", "sha256:x")).to.equal(false);
    });

    it("should validate required order hash fields", async function () {
      const { contract } = await loadFixture(deployFixture);

      await expect(contract.storeOrderHash("", "sha256:ok")).to.be.revertedWith(
        "Order ID required",
      );
      await expect(contract.storeOrderHash("ORD20260213004_080000", "")).to.be.revertedWith(
        "Data hash required",
      );
    });
  });

  describe("Anomaly records", function () {
    it("should start anomaly and append id to order index", async function () {
      const { contract } = await loadFixture(deployFixture);
      const startTime = (await time.latest()) + 1;

      await expect(
        contract.startAnomaly(
          "ORD20260213005_080000",
          "temperature",
          650,
          startTime,
          "base64:encrypted_payload",
        ),
      )
        .to.emit(contract, "AnomalyStarted")
        .withArgs(1n, "ORD20260213005_080000", "temperature", 650, startTime);

      expect(await contract.anomalyCount()).to.equal(1n);
      const ids = await contract.getAnomaliesByOrder("ORD20260213005_080000");
      expect(ids).to.deep.equal([1n]);

      const anomaly = await contract.getAnomaly(1n);
      expect(anomaly.orderId).to.equal("ORD20260213005_080000");
      expect(anomaly.anomalyType).to.equal("temperature");
      expect(anomaly.triggerValue).to.equal(650n);
      expect(anomaly.startTime).to.equal(BigInt(startTime));
      expect(anomaly.endTime).to.equal(0n);
      expect(anomaly.peakValue).to.equal(650n);
      expect(anomaly.closed).to.equal(false);
      expect(anomaly.encryptedInfo).to.equal("base64:encrypted_payload");
    });

    it("should close anomaly with valid end time", async function () {
      const { contract } = await loadFixture(deployFixture);
      const startTime = (await time.latest()) + 10;
      const endTime = startTime + 30;

      await contract.startAnomaly(
        "ORD20260213006_080000",
        "humidity",
        9200,
        startTime,
        "base64:enc",
      );

      await expect(contract.closeAnomaly(1n, endTime, 9800))
        .to.emit(contract, "AnomalyClosed")
        .withArgs(1n, endTime, 9800);

      const anomaly = await contract.getAnomaly(1n);
      expect(anomaly.closed).to.equal(true);
      expect(anomaly.endTime).to.equal(BigInt(endTime));
      expect(anomaly.peakValue).to.equal(9800n);
    });

    it("should block invalid close actions", async function () {
      const { contract } = await loadFixture(deployFixture);
      const startTime = (await time.latest()) + 100;

      await expect(contract.closeAnomaly(1n, startTime + 1, 100)).to.be.revertedWith(
        "Anomaly not found",
      );

      await contract.startAnomaly("ORD20260213007_080000", "pressure", 101325, startTime, "enc");

      await expect(contract.closeAnomaly(1n, startTime, 101500)).to.be.revertedWith(
        "End time must be after start time",
      );

      await contract.closeAnomaly(1n, startTime + 1, 101500);
      await expect(contract.closeAnomaly(1n, startTime + 2, 101600)).to.be.revertedWith(
        "Anomaly already closed",
      );
    });

    it("should enforce authorization and required fields when starting anomaly", async function () {
      const { contract, other } = await loadFixture(deployFixture);
      const now = await time.latest();

      await expect(
        contract.connect(other).startAnomaly("ORD20260213008_080000", "temperature", 1, now + 1, "enc"),
      ).to.be.revertedWith("Not authorized");

      await expect(
        contract.startAnomaly("", "temperature", 1, now + 1, "enc"),
      ).to.be.revertedWith("Order ID required");
      await expect(
        contract.startAnomaly("ORD20260213008_080000", "", 1, now + 1, "enc"),
      ).to.be.revertedWith("Anomaly type required");
      await expect(
        contract.startAnomaly("ORD20260213008_080000", "temperature", 1, 0, "enc"),
      ).to.be.revertedWith("Invalid start time");
      await expect(
        contract.startAnomaly("ORD20260213008_080000", "temperature", 1, now + 1, ""),
      ).to.be.revertedWith("Encrypted info required");
    });
  });
});
