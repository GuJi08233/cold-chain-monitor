import { buildModule } from "@nomicfoundation/hardhat-ignition/modules";

const ColdChainMonitorV3Module = buildModule("ColdChainMonitorV3Module", (m) => {
  const contract = m.contract("ColdChainMonitorV3");
  return { contract };
});

export default ColdChainMonitorV3Module;
