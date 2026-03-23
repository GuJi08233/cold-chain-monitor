import fs from "node:fs";
import path from "node:path";
import hre from "hardhat";

function makeString(length: number, fill = "x"): string {
  if (length <= 0) {
    return "";
  }
  return fill.repeat(length);
}

function toEth(wei: bigint): string {
  return hre.ethers.formatEther(wei);
}

function loadContractAddress(): string {
  const addressFile = path.resolve(
    __dirname,
    "../ignition/deployments/chain-233/deployed_addresses.json",
  );
  const data = JSON.parse(fs.readFileSync(addressFile, "utf-8")) as Record<
    string,
    string
  >;
  const address = data["ColdChainMonitorV2Module#ColdChainMonitorV2"];
  if (!address) {
    throw new Error("未找到 V2 已部署合约地址");
  }
  return address;
}

async function main() {
  const provider = hre.ethers.provider;
  const signer = (await hre.ethers.getSigners())[0];
  const contractAddress = loadContractAddress();
  const contract = await hre.ethers.getContractAt(
    "ColdChainMonitorV2",
    contractAddress,
    signer,
  );

  const feeData = await provider.getFeeData();
  const gasPrice = feeData.gasPrice ?? 0n;

  const printLine = (name: string, gas: bigint) => {
    const costWei = gas * gasPrice;
    console.log(
      `[${name}] gas=${gas.toString()} | est_cost=${toEth(costWei)} ETH`,
    );
  };

  console.log("=== ALY Gas Estimate (ColdChainMonitorV2) ===");
  console.log(`network=${hre.network.name}`);
  console.log(`contract=${contractAddress}`);
  console.log(`from=${signer.address}`);
  console.log(`gasPrice=${gasPrice.toString()} wei`);
  console.log("");

  const randomAddress = hre.ethers.Wallet.createRandom().address;
  const addAuthorizedGas = await contract.addAuthorized.estimateGas(randomAddress);
  printLine("addAuthorized", addAuthorizedGas);

  const orderLegacy = `ORD${Date.now()}_V2LEGACY`;
  const dataHash = `sha256:${makeString(64, "a")}`;
  const storeLegacyGas = await contract.storeOrderHash.estimateGas(orderLegacy, dataHash);
  printLine("storeOrderHash(legacy)", storeLegacyGas);

  const orderDigest = `ORD${Date.now()}_V2DIGEST`;
  const digest = hre.ethers.keccak256(hre.ethers.toUtf8Bytes(dataHash));
  const storeDigestGas = await contract.storeOrderHashDigest.estimateGas(orderDigest, digest);
  printLine("storeOrderHashDigest(low-gas)", storeDigestGas);

  const now = BigInt(Math.floor(Date.now() / 1000));
  const enc = makeString(256, "e");
  const encHash = hre.ethers.keccak256(hre.ethers.toUtf8Bytes(enc));
  const startLegacyGas = await contract.startAnomaly.estimateGas(
    orderLegacy,
    "temperature",
    2667,
    now,
    enc,
  );
  printLine("startAnomaly(legacy,enc=256)", startLegacyGas);

  const startLiteGas = await contract.startAnomalyLite.estimateGas(
    `${orderLegacy}_LITE`,
    "temperature",
    2667,
    now + 1n,
    encHash,
  );
  printLine("startAnomalyLite(low-gas)", startLiteGas);

  // warm call: same order & type
  const startLiteWarmGas = await contract.startAnomalyLite.estimateGas(
    `${orderLegacy}_LITE`,
    "temperature",
    2667,
    now + 2n,
    encHash,
  );
  printLine("startAnomalyLite(low-gas,warm)", startLiteWarmGas);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
