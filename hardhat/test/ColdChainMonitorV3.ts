import { anyValue } from "@nomicfoundation/hardhat-chai-matchers/withArgs";
import { loadFixture, time } from "@nomicfoundation/hardhat-toolbox/network-helpers";
import { expect } from "chai";
import hre from "hardhat";

describe("ColdChainMonitorV3", function () {
  async function deployFixture() {
    const [owner, uploader, other] = await hre.ethers.getSigners();
    const Factory = await hre.ethers.getContractFactory("ColdChainMonitorV3");
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

  describe("driver anchors and anomaly records", function () {
    it("supports explicit driver anchor upsert/get", async function () {
      const { contract, owner } = await loadFixture(deployFixture);
      const orderId = "ORD20260224005_07383600";
      const driverRefHash = hre.ethers.keccak256(hre.ethers.toUtf8Bytes("driver#1001"));
      const idCommit = hre.ethers.keccak256(hre.ethers.toUtf8Bytes("id-commit"));
      const profileHash = hre.ethers.keccak256(hre.ethers.toUtf8Bytes("profile-hash"));

      await expect(contract.upsertDriverAnchor(orderId, driverRefHash, idCommit, profileHash))
        .to.emit(contract, "DriverAnchorUpserted")
        .withArgs(orderId, driverRefHash, idCommit, profileHash, anyValue, owner.address);

      const anchor = await contract.getDriverAnchor(orderId);
      expect(anchor.driverRefHash).to.equal(driverRefHash);
      expect(anchor.idCommit).to.equal(idCommit);
      expect(anchor.profileHash).to.equal(profileHash);
      expect(anchor.exists).to.equal(true);
      expect(anchor.uploader).to.equal(owner.address);
    });

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

    it("supports lite anomaly + driver anchor in one tx", async function () {
      const { contract, owner } = await loadFixture(deployFixture);
      const startTime = (await time.latest()) + 5;
      const infoHash = hre.ethers.keccak256(hre.ethers.toUtf8Bytes("encrypted-payload"));
      const driverRefHash = hre.ethers.keccak256(hre.ethers.toUtf8Bytes("driver#2002"));
      const idCommit = hre.ethers.keccak256(hre.ethers.toUtf8Bytes("id-commit-2002"));
      const profileHash = hre.ethers.keccak256(hre.ethers.toUtf8Bytes("profile-2002"));

      const tx1 = await contract.startAnomalyLiteWithAnchor(
        "ORD20260224004_07383600",
        "humidity",
        7890,
        startTime,
        infoHash,
        driverRefHash,
        idCommit,
        profileHash,
      );
      const receipt1 = await tx1.wait();
      expect(receipt1?.status).to.equal(1);

      await expect(
        contract.getDriverAnchor("ORD20260224004_07383600"),
      ).to.not.be.reverted;
      const anchor = await contract.getDriverAnchor("ORD20260224004_07383600");
      expect(anchor.driverRefHash).to.equal(driverRefHash);
      expect(anchor.idCommit).to.equal(idCommit);
      expect(anchor.profileHash).to.equal(profileHash);
      expect(anchor.exists).to.equal(true);
      expect(anchor.uploader).to.equal(owner.address);

      const tx2 = await contract.startAnomalyLiteWithAnchor(
        "ORD20260224004_07383600",
        "humidity",
        7890,
        startTime + 1,
        infoHash,
        driverRefHash,
        idCommit,
        profileHash,
      );
      const receipt2 = await tx2.wait();
      expect(receipt2?.status).to.equal(1);
      expect(receipt2?.gasUsed).to.be.lessThan(receipt1?.gasUsed ?? 0n);

      await expect(
        contract.startAnomalyLite(
          "ORD20260224004_07383600",
          "humidity",
          7890,
          startTime + 2,
          infoHash,
        ),
      )
        .to.emit(contract, "AnomalyStartedLite")
        .withArgs(3n, "ORD20260224004_07383600", "humidity", 7890, startTime + 2, infoHash);

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
