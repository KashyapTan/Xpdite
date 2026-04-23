import fs from 'fs';
import path from 'path';

export function bundlePythonResources(projectRoot: string = process.cwd()): void {
    const resourcesDir = path.join(projectRoot, 'dist-electron', 'resources');
    const pythonDir = path.join(resourcesDir, 'python');
    
    if (!fs.existsSync(resourcesDir)) {
        fs.mkdirSync(resourcesDir, { recursive: true });
    }
    
    if (!fs.existsSync(pythonDir)) {
        fs.mkdirSync(pythonDir, { recursive: true });
    }
    
    console.log('Bundling Python resources...');
    
    // Copy Python source code
    const sourceDir = path.join(projectRoot, 'source');
    const targetSourceDir = path.join(pythonDir, 'source');
    
    if (fs.existsSync(sourceDir)) {
        copyDirectorySync(sourceDir, targetSourceDir);
        console.log('Python source code copied');
    }
    
    // Copy Python executable and dependencies from virtual environment
    const venvDir = path.join(projectRoot, '.venv');
    if (fs.existsSync(venvDir)) {
        const venvScriptsDir = path.join(venvDir, 'Scripts');
        const venvLibDir = path.join(venvDir, 'Lib');
        
        // Copy Python executable
        const pythonExe = path.join(venvScriptsDir, 'python.exe');
        if (fs.existsSync(pythonExe)) {
            fs.copyFileSync(pythonExe, path.join(pythonDir, 'python.exe'));
            console.log('Python executable copied');
        }
        
        // Copy essential DLLs
        const dllsDir = path.join(venvScriptsDir);
        if (fs.existsSync(dllsDir)) {
            const dlls = fs.readdirSync(dllsDir).filter(file => file.endsWith('.dll'));
            dlls.forEach(dll => {
                fs.copyFileSync(
                    path.join(dllsDir, dll), 
                    path.join(pythonDir, dll)
                );
            });
            console.log('DLLs copied');
        }
        
        // Copy Python libraries
        if (fs.existsSync(venvLibDir)) {
            const targetLibDir = path.join(pythonDir, 'Lib');
            copyDirectorySync(venvLibDir, targetLibDir);
            console.log('Python libraries copied');
        }
    }
    
    console.log('Python resources bundled successfully');
}

function copyDirectorySync(src: string, dest: string): void {
    if (!fs.existsSync(dest)) {
        fs.mkdirSync(dest, { recursive: true });
    }
    
    const entries = fs.readdirSync(src, { withFileTypes: true });
    
    for (const entry of entries) {
        const srcPath = path.join(src, entry.name);
        const destPath = path.join(dest, entry.name);
        
        if (entry.isDirectory()) {
            copyDirectorySync(srcPath, destPath);
        } else {
            fs.copyFileSync(srcPath, destPath);
        }
    }
}
