import { buildModule } from "@nomicfoundation/hardhat-ignition/modules";

const ColdChainMonitorV3R2Module = buildModule("ColdChainMonitorV3R2Module", (m) => {
  const contract = m.contract("ColdChainMonitorV3");
  return { contract };
});

export default ColdChainMonitorV3R2Module;
