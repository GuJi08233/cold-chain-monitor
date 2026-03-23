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
  const address = data["ColdChainMonitorModule#ColdChainMonitor"];
  if (!address) {
    throw new Error("未找到已部署合约地址");
  }
  return address;
}

async function findOpenAnomalyId(
  contract: any,
  maxScan = 300,
): Promise<{ anomalyId: bigint; startTime: bigint; triggerValue: bigint } | null> {
  const count = (await contract.anomalyCount()) as bigint;
  if (count <= 0n) {
    return null;
  }
  const start = count > BigInt(maxScan) ? count - BigInt(maxScan) + 1n : 1n;
  for (let id = count; id >= start; id -= 1n) {
    try {
      const row = await contract.getAnomaly(id);
      if (row && row.closed === false) {
        return {
          anomalyId: id,
          startTime: BigInt(row.startTime),
          triggerValue: BigInt(row.triggerValue),
        };
      }
    } catch {
      // ignore invalid id
    }
    if (id === 1n) {
      break;
    }
  }
  return null;
}

async function main() {
  const provider = hre.ethers.provider;
  const signer = (await hre.ethers.getSigners())[0];
  const contractAddress = loadContractAddress();
  const contract = await hre.ethers.getContractAt(
    "ColdChainMonitor",
    contractAddress,
    signer,
  );
  const Factory = await hre.ethers.getContractFactory("ColdChainMonitor", signer);

  const feeData = await provider.getFeeData();
  const gasPrice = feeData.gasPrice ?? 0n;
  const blockNo = await provider.getBlockNumber();
  const chainId = (await provider.getNetwork()).chainId;

  console.log("=== ALY Gas Estimate (eth_estimateGas) ===");
  console.log(`network=${hre.network.name}`);
  console.log(`chainId=${chainId.toString()}`);
  console.log(`block=${blockNo}`);
  console.log(`contract=${contractAddress}`);
  console.log(`from=${signer.address}`);
  console.log(`gasPrice=${gasPrice.toString()} wei`);
  console.log("");

  const printLine = (name: string, gas: bigint) => {
    const costWei = gas * gasPrice;
    console.log(
      `[${name}] gas=${gas.toString()} | est_cost=${toEth(costWei)} ETH`,
    );
  };

  const deployTx = await Factory.getDeployTransaction();
  const deployGas = await provider.estimateGas({
    from: signer.address,
    data: deployTx.data ?? "0x",
  });
  printLine("deploy(ColdChainMonitor)", deployGas);

  const randomAddress = hre.ethers.Wallet.createRandom().address;
  const addAuthorizedGas = await contract.addAuthorized.estimateGas(randomAddress);
  printLine("addAuthorized", addAuthorizedGas);

  const orderId = `ORD${Date.now()}_GAS`;
  const dataHash = `sha256:${makeString(64, "a")}`;
  const storeOrderHashGas = await contract.storeOrderHash.estimateGas(orderId, dataHash);
  printLine("storeOrderHash", storeOrderHashGas);

  const now = BigInt(Math.floor(Date.now() / 1000));
  const start64 = await contract.startAnomaly.estimateGas(
    `${orderId}_A64`,
    "temperature",
    2667,
    now,
    makeString(64, "e"),
  );
  printLine("startAnomaly(enc=64)", start64);

  const start256 = await contract.startAnomaly.estimateGas(
    `${orderId}_A256`,
    "temperature",
    2667,
    now + 1n,
    makeString(256, "e"),
  );
  printLine("startAnomaly(enc=256)", start256);

  const start512 = await contract.startAnomaly.estimateGas(
    `${orderId}_A512`,
    "temperature",
    2667,
    now + 2n,
    makeString(512, "e"),
  );
  printLine("startAnomaly(enc=512)", start512);

  const openAnomaly = await findOpenAnomalyId(contract);
  if (openAnomaly) {
    const closeEnd =
      now > openAnomaly.startTime ? now : openAnomaly.startTime + 1n;
    const closeGas = await contract.closeAnomaly.estimateGas(
      openAnomaly.anomalyId,
      closeEnd,
      openAnomaly.triggerValue,
    );
    printLine(`closeAnomaly(id=${openAnomaly.anomalyId.toString()})`, closeGas);
  } else {
    console.log("[closeAnomaly] 未找到可关闭的链上异常，跳过估算");
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
