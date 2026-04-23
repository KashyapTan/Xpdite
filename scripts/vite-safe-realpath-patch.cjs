const { EventEmitter } = require('node:events');
const childProcess = require('node:child_process');

const originalExec = childProcess.exec;

function createStubChildProcess() {
  const child = new EventEmitter();
  child.kill = () => true;
  child.stdout = null;
  child.stderr = null;
  return child;
}

childProcess.exec = function patchedExec(command, ...args) {
  if (process.platform === 'win32' && typeof command === 'string' && command.trim().toLowerCase() === 'net use') {
    const callback = typeof args.at(-1) === 'function' ? args.at(-1) : null;
    const child = createStubChildProcess();

    process.nextTick(() => {
      callback?.(null, '', '');
      child.emit('close', 0);
      child.emit('exit', 0);
    });

    return child;
  }

  return originalExec.call(this, command, ...args);
};
