# Jupyter Lab MicroPython Kernel
Jupyter Lab kernel to interact with a MicroPython ESP8266 or ESP32 over its serial REPL.

## Installation

First clone this repository to a directory using TortoiseGIT or with the shell command (ie on a command line):
```shell script
git clone https://github.com/zhouzaihang/jupyterlab_micropython_kernel.git
cd jupyterlab_micropython_kernel
```

Then install this library (in editable mode) into Python3 using the shell command:
```shell script
pip install -e .
```

This creates a small file pointing to this directory in the python/../site-packages 
directory, and makes it possible to "git update" the library later as it gets improved.
(Things can go wrong here, and you might need "pip3" or "sudo pip" if you have 
numerous different versions of python installed

Install the kernel into jupyter itself using the shell command:

```shell script
python -m jupyterlab_micropython_kernel.install
```

(This creates the small file ".local/share/jupyter/kernels/micropython/kernel.json" 
that jupyter uses to reference it's kernels

To find out where your kernelspecs are stored, you can type:
```shell script
jupyter kernelspec list
```

## %Cell Commands

### %serialconnect [SERIAL PORT] [BAUDRATE]

connect serial connection

eg:
```jupyter
%serialconnect /dev/ttyUSB0 115200
```

### %disconnect [--raw]

disconnects from web/serial connection

eg:
```jupyter
%disconnects
```

### %ls [--recurse] [dirname]

list files on the device

eg:
```jupyter
%ls
%ls lib
```

### %remove filename

remove file on the device

eg:
```jupyter
%remove main.py
```

### %rmdir directory

remove directory on the device

eg:
```jupyter
%rmdir lib
```

### %lsmagic

list all magic commands

### %rebootdevice

soft reboots device

```jupyter
%rebootdevice
```

### %uploadmain [--source SOURCE] [--reboot]

convert a .py or .ipynb file to a main.py and upload it

```jupyter
%uploadmain
%uploadmain dht11.ipynb
```


## TODO
1. Add %uploadproject: convert all .ipynb to .py and upload to device.
1. Writing user manuals.
1. Make some demo.
1. Add %meminfo: Shows RAM size/used/free/use% info.
1. Fix bug.
1. ...

## Background
This JupyterLab MicroPython Kernel is heavily based on the amazing work done on https://github.com/goatchurchprime/jupyter_micropython_kernel

Their device connection library has been replaced by upydevice latest classes SERIAL_DEVICE and WS_DEVICE that allows both serial and websocket (WebREPL) connections.
The kernel has also been reworked to support autocompletions on tab which works for MicroPython, iPython and %cell magic commands.
Some %cell magic commands were dropped and some new were added e.g: %remove %rmdir %uploadmain
