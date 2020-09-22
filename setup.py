from pathlib import Path
from setuptools import setup

# Get the long description from the README file
project = Path(__file__).parent
with (project / 'README.md').open(encoding='utf-8') as f:
    long_description = f.read()

setup(name="jupyterlab_micropython_kernel",
      version="0.0.6",
      description=long_description,
      author='ZhouZaihang, Julian Todd, Tony DiCola',
      author_email='zaihang822@gamil.com',
      keywords='jupyterlab micropython',
      url='https://github.com/zhouzaihang/jupyterlab_micropython_kernel',
      license='MIT',
      packages=['jupyterlab_micropython_kernel'],
      install_requires=['pyserial>=3.4', 'websocket-client>=0.44', 'ipykernel', 'nbconvert', 'nbformat']
)