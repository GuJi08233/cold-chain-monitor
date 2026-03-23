import type { HardhatUserConfig } from "hardhat/config";
import "@nomicfoundation/hardhat-toolbox";

// 1. 在文件顶部导入 dotenv/config, 它会自动加载 .env 文件
import "dotenv/config";

// 2. 从 process.env 中读取环境变量
const ALY_RPC_URL = process.env.ALY_RPC_URL || "";
const SEPOLIA_RPC_URL = process.env.SEPOLIA_RPC_URL || "";
const SOLC_OPTIMIZER_ENABLED =
  (process.env.SOLC_OPTIMIZER_ENABLED || "false").toLowerCase() === "true";
const SOLC_OPTIMIZER_RUNS = Number(process.env.SOLC_OPTIMIZER_RUNS || "200");

function normalizePrivateKey(rawValue: string | undefined): string | undefined {
  const value = (rawValue || "").trim().replace(/^"|"$/g, "");
  if (!value) {
    return undefined;
  }
  return value.startsWith("0x") ? value : `0x${value}`;
}

const ALY_KEY = normalizePrivateKey(process.env.ALY_KEY);
const SEPOLIA_KEY = normalizePrivateKey(process.env.SEPOLIA_KEY);

function buildNetworkConfig(url: string, privateKey: string | undefined, chainId: number) {
  const normalizedUrl = url.trim().replace(/^"|"$/g, "");
  if (!normalizedUrl || !privateKey) {
    return undefined;
  }
  return {
    url: normalizedUrl,
    accounts: [privateKey],
    chainId,
  };
}

const alyNetwork = buildNetworkConfig(ALY_RPC_URL, ALY_KEY, 233);
const sepoliaNetwork = buildNetworkConfig(SEPOLIA_RPC_URL, SEPOLIA_KEY, 11155111);

const config: HardhatUserConfig = {
  solidity: {
    version: "0.8.28",
    settings: {
      optimizer: {
        enabled: SOLC_OPTIMIZER_ENABLED,
        runs: SOLC_OPTIMIZER_RUNS,
      },
    },
  },

  networks: {
    ...(alyNetwork ? { aly: alyNetwork } : {}),
    ...(sepoliaNetwork ? { sepolia: sepoliaNetwork } : {}),
  },
};

export default config;
