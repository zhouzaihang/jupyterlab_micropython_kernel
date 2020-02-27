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

eg.
```jupyter
%serialconnect --port=/dev/ttyUSB0 --baudrate=115200
```

### %disconnect [--raw]

disconnects from web/serial connection

eg.
```jupyter
%disconnect
```

### %ls [--recurse] [dirname]

list files on the device

eg.
```jupyter
%ls
```

eg. list directory recursion:
```jupyter
%ls -r
```

eg. list specific directory:
```jupyter
%ls lib
```


### %remove filename

remove file on the device

eg.
```jupyter
%remove main.py
```

### %rmdir directory

remove directory on the device

eg.
```jupyter
%rmdir lib
```

### %lsmagic

list all magic commands

### %rebootdevice

soft reboots device

eg.
```jupyter
%rebootdevice
```

### %uploadmain [--source SOURCE] [--reboot]

convert a .py or .ipynb file to a main.py and upload it

eg. upload main.py or main.ipynb:
```jupyter
%uploadmain
```

eg. upload specific path main.py or main.ipynb:
```jupyter
%uploadmain --source lib/main.ipynb
```

eg. convert and upload specific path *.py or *.ipynb as main.py:
```jupyter
%uploadmain --source lib/dht11.ipynb
```

eg. upload and soft reboot:
```jupyter
%uploadmain --source lib/main.ipynb -r
```

### %uploadproject [-h] [--source SOURCE] [--reboot] [--emptydevice] [--onlypy]

Upload all files in the specified folder to the microcontroller's file system while convert all .ipynb files to .py files

eg. upload specific directory as project root directory:

```jupyter
%uploadproject --source dht11
```

eg. reboot after uploaded:

```jupyter
%uploadproject --source dht11 -r
```

eg. remove all file in the divice before upload:

```jupyter
%uploadproject --source dht11 -e
```

eg. only upload .py or .ipynb files to the device:

```jupyter
%uploadproject --source dht11 -r -e -py
```

### %meminfo
    
show RAM size/used/free/use% info

eg.
```jupyter
%meminfo

Memmory         Size        Used       Avail        Use%    
RAM          116.188 KB   7.859 KB   108.328 KB    6.8 %
```

### %sendfile [destinationfilename] [--append] [--mkdir] [--binary] [--execute] [--source [SOURCE]] [--quiet] [--QUIET]

send a file to the microcontroller's file system

positional arguments:
- destinationfilename

optional arguments:
- --append, -a
- --mkdir, -d
- --binary, -b
- --execute, -x
- --source [SOURCE]    source file
- --quiet, -q
- --QUIET, -Q

eg. send a local text file (`ModbusSlave/const.py`) to the microcontroller's file system as `const.py`:

```jupyter
%sendfile const.py --source ModbusSlave/const.py
```

eg.  send a local text file (`ModbusSlave/const.py`) to the microcontroller's file system as `ModbusSlave/const.py`

> When you need to create a new folder, you need to use the -d parameter. 
> If the `XXX` folder is not on your device and your command does not have a `-d` parameter, you would get a error.

```jupyter
%sendfile ModbusSlave/const.py --source ModbusSlave/const.py -d
```

eg. Add local text file content to a text file that already exists on the device:

```jupyter
%sendfile const.py --source ModbusSlave/const.py -a
```

eg. send a local binary file (`ModbusSlave/const.mpy`) to the microcontroller's file system as `const.mpy`:

```jupyter
%sendfile const.mpy --source ModbusSlave/const.mpy -b
```

eg. send a local binary file (`ModbusSlave/const.mpy`) to the microcontroller's file system as `const.mpy` and execute it:

```jupyter
%sendfile const.mpy --source ModbusSlave/const.mpy -b -x
```

## Q&A

1. interrupt endless code in jupyterlab:
    
    If you run endless loop code in Jupyter Lab, you can abort the run through the Interrupt Kernel.(`menu->Kernel->Interrupt Kernel` or `Keyboard shortcut: (i, i)`)
    
    eg:
    
    ```jupyter
    import utime
    while True:
        print("Hello")
        utime.sleep(1)
    ```

    click `menu->Kernel->Interrupt Kernel` or press on `Keyboard shortcut: (i, i)`

## TODO
1. ~~Add %uploadproject: convert all .ipynb to .py and upload to device.~~
1. Writing user manuals.
1. Make some demo.
1. ~~Add %meminfo: Shows RAM size/used/free/use% info.~~
1. Fix bug.
1. ...

## Background
This JupyterLab MicroPython Kernel is heavily based on the amazing work done on https://github.com/goatchurchprime/jupyter_micropython_kernel

The kernel has also been reworked to support autocompletions on tab which works for MicroPython, iPython and %cell magic commands.
Some %cell magic commands were dropped and some new were added e.g: %remove %rmdir %uploadmain
