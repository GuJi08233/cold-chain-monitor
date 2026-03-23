import { buildModule } from "@nomicfoundation/hardhat-ignition/modules";

const ColdChainMonitorModule = buildModule("ColdChainMonitorModule", (m) => {
  const coldChainMonitor = m.contract("ColdChainMonitor", []);
  return { coldChainMonitor };
});

export default ColdChainMonitorModule;
