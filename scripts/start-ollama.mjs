import { spawn, spawnSync } from 'node:child_process';

function detectGPU() {
  // 1. NVIDIA — nvidia-smi is available and exits cleanly
  const nvidiaSmi = spawnSync('nvidia-smi', [], { stdio: 'ignore', shell: false });
  if (nvidiaSmi.status === 0) return 'nvidia';

  // 2. AMD — HIP_PATH is set by the ROCm/HIP installer on Windows
  if (process.env.HIP_PATH || process.env.HIP_PATH_64 || process.env.AMDRMPATH) return 'amd';

  return 'cpu';
}

const gpu = detectGPU();
console.log(`[start-ollama] detected: ${gpu}`);

const base = { ...process.env };

// Clear all GPU selectors first so there are no cross-driver conflicts
delete base.CUDA_VISIBLE_DEVICES;
delete base.HIP_VISIBLE_DEVICES;
delete base.HSA_OVERRIDE_GFX_VERSION;
delete base.GGML_VK_VISIBLE_DEVICES;
delete base.OLLAMA_GPU_DRIVER;

let env;
if (gpu === 'nvidia') {
  env = {
    ...base,
    // Let ollama auto-detect CUDA; just ensure device 0 is visible
    CUDA_VISIBLE_DEVICES: process.env.CUDA_VISIBLE_DEVICES ?? '0',
  };
} else if (gpu === 'amd') {
  env = {
    ...base,
    // Force Vulkan — works on Windows where ROCm HIP can conflict with GPU detection.
    // Do NOT restrict GGML_VK_VISIBLE_DEVICES so ollama enumerates all Vulkan devices
    // and picks the best one (avoids accidentally pinning to iGPU at index 0).
    OLLAMA_GPU_DRIVER: 'vulkan',
  };
} else {
  // CPU-only — no GPU vars needed
  env = { ...base };
}

const proc = spawn('ollama', ['serve'], {
  env,
  stdio: 'ignore',   // suppress all output — no log flooding
  detached: false,
});

proc.on('error', (err) => {
  console.error('[start-ollama] failed to start ollama:', err.message);
  process.exit(1);
});

proc.on('exit', (code) => {
  process.exit(code ?? 0);
});

// // Kill ollama when this script exits (Ctrl+C, bun dev shutdown, etc.)
// function cleanup() {
//   try { proc.kill(); } catch {}
//   process.exit(0);
// }
// process.on('exit', () => { try { proc.kill(); } catch {} });
// process.on('SIGINT', cleanup);
// process.on('SIGTERM', cleanup);

