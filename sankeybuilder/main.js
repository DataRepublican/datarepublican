import { SankeyBuilderViewModel } from "./viewModel.js";
import { idbStore } from "./store.js";
import { bindView } from "./view.js";

const vm = new SankeyBuilderViewModel({ store: idbStore() });
const root = document.getElementById("sb");

bindView(root, vm);
vm.bootFromLocation();
