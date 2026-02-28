# Clear HIP/ROCm vars that conflict with Vulkan detection
$env:HIP_VISIBLE_DEVICES = $null
$env:HSA_OVERRIDE_GFX_VERSION = $null
$env:ROCR_VISIBLE_DEVICES = $null

# Load Vulkan-relevant vars fresh from registry
$reg = [System.Environment]

$vars = @(
    'GGML_VK_VISIBLE_DEVICES',
    'OLLAMA_GPU_DRIVER',
    'OLLAMA_GPU_ENABLED',
    'OLLAMA_NUM_GPU',
    'OLLAMA_VULKAN'
)

foreach ($v in $vars) {
    $val = $reg::GetEnvironmentVariable($v, 'User')
    if (-not $val) { $val = $reg::GetEnvironmentVariable($v, 'Machine') }
    if ($val) { [System.Environment]::SetEnvironmentVariable($v, $val, 'Process') }
}

ollama serve
