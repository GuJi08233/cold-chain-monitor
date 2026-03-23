import { buildModule } from "@nomicfoundation/hardhat-ignition/modules";

const ColdChainMonitorV2Module = buildModule("ColdChainMonitorV2Module", (m) => {
  const contract = m.contract("ColdChainMonitorV2");
  return { contract };
});

export default ColdChainMonitorV2Module;
