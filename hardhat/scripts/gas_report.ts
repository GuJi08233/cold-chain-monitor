import hre from "hardhat";

function makeString(length: number, fill = "x"): string {
  if (length <= 0) {
    return "";
  }
  return fill.repeat(length);
}

async function main() {
  const [owner, uploader] = await hre.ethers.getSigners();
  const Factory = await hre.ethers.getContractFactory("ColdChainMonitor");
  const deployTx = await Factory.deploy();
  const deployReceipt = await deployTx.deploymentTransaction()?.wait();
  const contract = deployTx;
  await contract.waitForDeployment();

  const provider = hre.ethers.provider;
  const feeData = await provider.getFeeData();
  const gasPrice = feeData.gasPrice ?? 0n;

  const toNative = (gasUsed: bigint): string => {
    if (gasPrice <= 0n) {
      return "N/A";
    }
    const weiCost = gasUsed * gasPrice;
    return hre.ethers.formatEther(weiCost);
  };

  const reportTx = async (name: string, txPromise: Promise<any>) => {
    const tx = await txPromise;
    const receipt = await tx.wait();
    const gasUsed = receipt?.gasUsed ?? 0n;
    const gasPriceInReceipt = receipt?.gasPrice ?? gasPrice;
    const costWei = gasUsed * gasPriceInReceipt;
    console.log(
      `[${name}] gasUsed=${gasUsed.toString()} | gasPrice=${gasPriceInReceipt.toString()} wei | cost=${hre.ethers.formatEther(costWei)} ETH`,
    );
    return receipt;
  };

  console.log("=== ColdChainMonitor Gas Report ===");
  console.log(`contract=${await contract.getAddress()}`);
  console.log(`network=${hre.network.name}`);
  console.log(`owner=${owner.address}`);
  console.log(`uploader=${uploader.address}`);
  console.log(
    `optimizer_enabled=${(process.env.SOLC_OPTIMIZER_ENABLED || "false").toLowerCase() === "true"}`,
  );
  console.log(`optimizer_runs=${process.env.SOLC_OPTIMIZER_RUNS || "200"}`);
  console.log(`suggested_gas_price=${gasPrice.toString()} wei`);
  if (deployReceipt?.gasUsed) {
    const deployCostWei = deployReceipt.gasUsed * (deployReceipt.gasPrice ?? gasPrice);
    console.log(
      `[deploy] gasUsed=${deployReceipt.gasUsed.toString()} | gasPrice=${(deployReceipt.gasPrice ?? gasPrice).toString()} wei | cost=${hre.ethers.formatEther(deployCostWei)} ETH`,
    );
  }
  console.log("");

  await reportTx("addAuthorized", contract.addAuthorized(uploader.address));

  await reportTx(
    "storeOrderHash",
    contract
      .connect(uploader)
      .storeOrderHash("ORD20260224001_07383600", `sha256:${makeString(64, "a")}`),
  );

  const now = Math.floor(Date.now() / 1000);
  const startTx = await reportTx(
    "startAnomaly(enc=256)",
    contract
      .connect(uploader)
      .startAnomaly(
        "ORD20260224001_07383600",
        "temperature",
        2667,
        now,
        makeString(256, "e"),
      ),
  );

  const logs = await contract.queryFilter(contract.filters.AnomalyStarted(), startTx.blockNumber, startTx.blockNumber);
  const anomalyId = logs[0]?.args?.anomalyId ?? 1n;

  await reportTx(
    "closeAnomaly",
    contract.connect(uploader).closeAnomaly(anomalyId, now + 120, 2888),
  );

  await reportTx(
    "startAnomaly(enc=64)",
    contract
      .connect(uploader)
      .startAnomaly(
        "ORD20260224002_07383600",
        "temperature",
        2667,
        now + 200,
        makeString(64, "e"),
      ),
  );

  await reportTx(
    "startAnomaly(enc=512)",
    contract
      .connect(uploader)
      .startAnomaly(
        "ORD20260224003_07383600",
        "temperature",
        2667,
        now + 300,
        makeString(512, "e"),
      ),
  );

  console.log("");
  console.log("=== Cost At Current gasPrice (ETH) ===");
  console.log(`gasPrice=${gasPrice.toString()} wei`);
  const sampleGas = [
    ["storeOrderHash", 155000n],
    ["startAnomaly(enc=64)", 260000n],
    ["startAnomaly(enc=256)", 380000n],
    ["startAnomaly(enc=512)", 540000n],
    ["closeAnomaly", 55000n],
  ] as const;
  for (const [name, gasUsed] of sampleGas) {
    console.log(`${name}: ~${toNative(gasUsed)} ETH`);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
