import { spawn, spawnSync } from 'node:child_process';

// ── Check if ollama is already running ──────────────────────────────
async function isOllamaRunning() {
  try {
    const res = await fetch('http://127.0.0.1:11434/', {
      signal: AbortSignal.timeout(2000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

const alreadyRunning = await isOllamaRunning();
if (alreadyRunning) {
  console.log('[start-ollama] ollama is already running — skipping launch');
  // Keep the process alive so bun dev doesn't think this script crashed.
  // It will exit when the parent (bun dev) sends SIGTERM.
  setInterval(() => {}, 60_000);
} else {
  await launchOllama();
}

async function launchOllama() {
  function detectGPU() {
    // 1. NVIDIA — nvidia-smi is available and exits cleanly
    const nvidiaSmi = spawnSync('nvidia-smi', [], { stdio: 'ignore', shell: false });
    if (nvidiaSmi.status === 0) return 'nvidia';

    // 2. AMD — HIP_PATH is set by the ROCm/HIP installer on Windows
    if (process.env.HIP_PATH || process.env.HIP_PATH_64 || process.env.AMDRMPATH) return 'amd';

    return 'cpu';
  }

  const gpu = detectGPU();
  console.log(`[start-ollama] detected GPU: ${gpu}`);

  const base = { ...process.env };

  // Clear all GPU selectors first so there are no cross-driver conflicts
  delete base.CUDA_VISIBLE_DEVICES;
  delete base.HIP_VISIBLE_DEVICES;
  delete base.HSA_OVERRIDE_GFX_VERSION;
  delete base.GGML_VK_VISIBLE_DEVICES;
  delete base.OLLAMA_GPU_DRIVER;

  // ── Performance tuning ────────────────────────────────────────────
  // Flash attention — uses less VRAM and is faster on modern GPUs
  base.OLLAMA_FLASH_ATTENTION = '1';
  // KV cache quantization — reduces VRAM usage for long contexts (q8_0 is a good balance)
  base.OLLAMA_KV_CACHE_TYPE = 'q8_0';

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

  console.log('[start-ollama] launching ollama serve (check system tray)');

  const proc = spawn('ollama', ['serve'], {
    env,
    stdio: 'ignore',   // suppress logs — no dev terminal flooding
    detached: true,     // own process group — survives Ctrl+C / bun dev shutdown
  });

  // Detach from this script so it doesn't keep the event loop alive
  proc.unref();

  proc.on('error', (err) => {
    console.error('[start-ollama] failed to start ollama:', err.message);
  });

  // Keep script alive so bun dev doesn't think it crashed
  setInterval(() => {}, 60_000);
}

