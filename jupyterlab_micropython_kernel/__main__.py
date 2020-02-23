import logging

from ipykernel.kernelapp import IPKernelApp
from .kernel import MicroPythonKernel

logging.basicConfig(level=logging.DEBUG)
IPKernelApp.launch_instance(kernel_class=MicroPythonKernel)
