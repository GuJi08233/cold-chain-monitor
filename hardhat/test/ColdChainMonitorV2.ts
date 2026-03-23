import { anyValue } from "@nomicfoundation/hardhat-chai-matchers/withArgs";
import { loadFixture, time } from "@nomicfoundation/hardhat-toolbox/network-helpers";
import { expect } from "chai";
import hre from "hardhat";

describe("ColdChainMonitorV2", function () {
  async function deployFixture() {
    const [owner, uploader, other] = await hre.ethers.getSigners();
    const Factory = await hre.ethers.getContractFactory("ColdChainMonitorV2");
    const contract = await Factory.deploy();
    return { contract, owner, uploader, other };
  }

  describe("access control", function () {
    it("sets deployer as owner and authorized uploader", async function () {
      const { contract, owner } = await loadFixture(deployFixture);
      expect(await contract.owner()).to.equal(owner.address);
      expect(await contract.isAuthorized(owner.address)).to.equal(true);
    });

    it("only owner can manage authorized uploaders", async function () {
      const { contract, uploader, other } = await loadFixture(deployFixture);
      await expect(contract.connect(other).addAuthorized(uploader.address))
        .to.be.revertedWithCustomError(contract, "NotOwner");
      await expect(contract.addAuthorized(uploader.address))
        .to.emit(contract, "AuthorizedAdded")
        .withArgs(uploader.address);
      expect(await contract.isAuthorized(uploader.address)).to.equal(true);
    });
  });

  describe("order hash", function () {
    it("supports legacy store/get/verify flow", async function () {
      const { contract, owner } = await loadFixture(deployFixture);
      const orderId = "ORD20260224001_07383600";
      const dataHash = "sha256:abc123";

      await expect(contract.storeOrderHash(orderId, dataHash))
        .to.emit(contract, "OrderHashStored")
        .withArgs(orderId, dataHash, anyValue);

      const [savedOrderId, savedHash, timestamp, uploader] = await contract.getOrderHash(orderId);
      expect(savedOrderId).to.equal(orderId);
      expect(savedHash).to.equal(dataHash);
      expect(timestamp).to.be.greaterThan(0n);
      expect(uploader).to.equal(owner.address);
      expect(await contract.verifyOrderHash(orderId, dataHash)).to.equal(true);
    });

    it("supports digest low-gas path", async function () {
      const { contract } = await loadFixture(deployFixture);
      const orderId = "ORD20260224002_07383600";
      const digest = hre.ethers.keccak256(hre.ethers.toUtf8Bytes("sha256:only-digest"));

      await expect(contract.storeOrderHashDigest(orderId, digest))
        .to.emit(contract, "OrderHashDigestStored")
        .withArgs(orderId, digest, anyValue);

      const [savedDigest] = await contract.getOrderHashDigest(orderId);
      expect(savedDigest).to.equal(digest);
      expect(await contract.verifyOrderHashDigest(orderId, digest)).to.equal(true);
      expect(await contract.verifyOrderHashDigest(orderId, hre.ethers.ZeroHash)).to.equal(false);
    });
  });

  describe("anomaly records", function () {
    it("supports legacy anomaly start/get/close flow", async function () {
      const { contract } = await loadFixture(deployFixture);
      const startTime = (await time.latest()) + 1;
      const endTime = startTime + 30;

      await expect(
        contract.startAnomaly(
          "ORD20260224003_07383600",
          "temperature",
          2667,
          startTime,
          "base64:encrypted_payload",
        ),
      )
        .to.emit(contract, "AnomalyStarted")
        .withArgs(1n, "ORD20260224003_07383600", "temperature", 2667, startTime);

      const anomaly = await contract.getAnomaly(1n);
      expect(anomaly.orderId).to.equal("ORD20260224003_07383600");
      expect(anomaly.anomalyType).to.equal("temperature");
      expect(anomaly.triggerValue).to.equal(2667n);
      expect(anomaly.closed).to.equal(false);
      expect(anomaly.encryptedInfo).to.equal("base64:encrypted_payload");

      await expect(contract.closeAnomaly(1n, endTime, 2888))
        .to.emit(contract, "AnomalyClosed")
        .withArgs(1n, endTime, 2888);
    });

    it("supports lite anomaly path with encrypted hash only", async function () {
      const { contract } = await loadFixture(deployFixture);
      const startTime = (await time.latest()) + 5;
      const infoHash = hre.ethers.keccak256(hre.ethers.toUtf8Bytes("encrypted-payload"));

      await expect(
        contract.startAnomalyLite(
          "ORD20260224004_07383600",
          "humidity",
          7890,
          startTime,
          infoHash,
        ),
      )
        .to.emit(contract, "AnomalyStarted")
        .withArgs(1n, "ORD20260224004_07383600", "humidity", 7890, startTime);

      await expect(
        contract.startAnomalyLite(
          "ORD20260224004_07383600",
          "humidity",
          7890,
          startTime + 1,
          infoHash,
        ),
      )
        .to.emit(contract, "AnomalyStartedLite")
        .withArgs(2n, "ORD20260224004_07383600", "humidity", 7890, startTime + 1, infoHash);

      const anomaly = await contract.getAnomaly(1n);
      expect(anomaly.encryptedInfo).to.equal("");
      expect(anomaly.anomalyType).to.equal("humidity");
      expect(anomaly.orderId).to.equal("ORD20260224004_07383600");

      const meta = await contract.getAnomalyMeta(1n);
      expect(meta.encryptedInfoHash).to.equal(infoHash);
      expect(meta.hasInlineEncryptedInfo).to.equal(false);
    });
  });
});
