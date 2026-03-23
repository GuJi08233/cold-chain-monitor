import hre from "hardhat";

type GasRow = {
  name: string;
  v1: bigint;
  v2Legacy: bigint;
  v2Lite?: bigint;
};

function makeString(length: number, fill = "x"): string {
  if (length <= 0) {
    return "";
  }
  return fill.repeat(length);
}

async function gasUsed(txPromise: Promise<any>): Promise<bigint> {
  const tx = await txPromise;
  const receipt = await tx.wait();
  return receipt?.gasUsed ?? 0n;
}

function pct(oldValue: bigint, newValue: bigint): string {
  if (oldValue === 0n) {
    return "N/A";
  }
  const diff = Number(newValue - oldValue);
  const base = Number(oldValue);
  return `${((diff / base) * 100).toFixed(2)}%`;
}

function printRows(rows: GasRow[]) {
  console.log("=== Gas Compare (V1 vs V2) ===");
  for (const row of rows) {
    const legacyPct = pct(row.v1, row.v2Legacy);
    const base = `[${row.name}] v1=${row.v1.toString()} | v2_legacy=${row.v2Legacy.toString()} (${legacyPct})`;
    if (row.v2Lite !== undefined) {
      const litePct = pct(row.v1, row.v2Lite);
      console.log(`${base} | v2_lite=${row.v2Lite.toString()} (${litePct})`);
    } else {
      console.log(base);
    }
  }
}

async function main() {
  const [owner, uploader] = await hre.ethers.getSigners();

  const V1Factory = await hre.ethers.getContractFactory("ColdChainMonitor");
  const V2Factory = await hre.ethers.getContractFactory("ColdChainMonitorV2");

  const v1 = await V1Factory.deploy();
  await v1.waitForDeployment();

  const v2 = await V2Factory.deploy();
  await v2.waitForDeployment();

  const rows: GasRow[] = [];

  const addV1 = await gasUsed(v1.addAuthorized(uploader.address));
  const addV2 = await gasUsed(v2.addAuthorized(uploader.address));
  rows.push({ name: "addAuthorized", v1: addV1, v2Legacy: addV2 });

  const order1 = "ORD_GAS_V1_001";
  const order2 = "ORD_GAS_V2_001";
  const order3 = "ORD_GAS_V2_LITE_001";
  const dataHash = `sha256:${makeString(64, "a")}`;
  const digest = hre.ethers.keccak256(hre.ethers.toUtf8Bytes(dataHash));

  const storeV1 = await gasUsed(v1.connect(uploader).storeOrderHash(order1, dataHash));
  const storeV2Legacy = await gasUsed(v2.connect(uploader).storeOrderHash(order2, dataHash));
  const storeV2Lite = await gasUsed(v2.connect(uploader).storeOrderHashDigest(order3, digest));
  rows.push({
    name: "storeOrderHash",
    v1: storeV1,
    v2Legacy: storeV2Legacy,
    v2Lite: storeV2Lite,
  });

  const now = Math.floor(Date.now() / 1000);
  const encryptedInfo = makeString(256, "e");
  const encryptedInfoHash = hre.ethers.keccak256(
    hre.ethers.toUtf8Bytes(encryptedInfo),
  );

  const startV1 = await gasUsed(
    v1
      .connect(uploader)
      .startAnomaly(order1, "temperature", 2667, now + 10, encryptedInfo),
  );
  const startV2Legacy = await gasUsed(
    v2
      .connect(uploader)
      .startAnomaly(order2, "temperature", 2667, now + 20, encryptedInfo),
  );
  const startV2Lite = await gasUsed(
    v2
      .connect(uploader)
      .startAnomalyLite(order3, "temperature", 2667, now + 30, encryptedInfoHash),
  );
  rows.push({
    name: "startAnomaly(enc=256)",
    v1: startV1,
    v2Legacy: startV2Legacy,
    v2Lite: startV2Lite,
  });

  const startV1Warm = await gasUsed(
    v1
      .connect(uploader)
      .startAnomaly(order1, "temperature", 2667, now + 40, encryptedInfo),
  );
  const startV2LegacyWarm = await gasUsed(
    v2
      .connect(uploader)
      .startAnomaly(order2, "temperature", 2667, now + 50, encryptedInfo),
  );
  const startV2LiteWarm = await gasUsed(
    v2
      .connect(uploader)
      .startAnomalyLite(order3, "temperature", 2667, now + 60, encryptedInfoHash),
  );
  rows.push({
    name: "startAnomaly(enc=256,warm)",
    v1: startV1Warm,
    v2Legacy: startV2LegacyWarm,
    v2Lite: startV2LiteWarm,
  });

  const anomalyIdV1 = await v1.anomalyCount();
  const anomalyIdV2Legacy = anomalyIdV1;
  const anomalyIdV2Lite = anomalyIdV1 + 2n;

  const closeV1 = await gasUsed(
    v1.connect(uploader).closeAnomaly(anomalyIdV1, now + 120, 2888),
  );
  const closeV2Legacy = await gasUsed(
    v2.connect(uploader).closeAnomaly(anomalyIdV2Legacy, now + 120, 2888),
  );
  const closeV2Lite = await gasUsed(
    v2.connect(uploader).closeAnomaly(anomalyIdV2Lite, now + 180, 2888),
  );
  rows.push({
    name: "closeAnomaly",
    v1: closeV1,
    v2Legacy: closeV2Legacy,
    v2Lite: closeV2Lite,
  });

  console.log(`v1=${await v1.getAddress()}`);
  console.log(`v2=${await v2.getAddress()}`);
  console.log(`owner=${owner.address}`);
  console.log(`uploader=${uploader.address}`);
  console.log(
    `optimizer_enabled=${(process.env.SOLC_OPTIMIZER_ENABLED || "false").toLowerCase() === "true"}`,
  );
  console.log(`optimizer_runs=${process.env.SOLC_OPTIMIZER_RUNS || "200"}`);
  printRows(rows);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
