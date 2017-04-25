from setuptools import setup, find_packages
from setuptools.command.install import install

class CustomInstall(install):
    """Ensures the module is placed at the root of the zip file."""

    def initialize_options(self):
        install.initialize_options(self)
        self.prefix = self.install_lib = ''

if __name__ == '__main__':
    import sys
    if sys.version_info[:2] != (3, 6):
        sys.exit('This package must be built with Python 3.6')
    setup(name='GarageDoorLambda',
          cmdclass=dict(install=CustomInstall),
          version='1.0.0',
          description='Garage door controlled access lambda',
          author='Jason Swails',
          author_email='jason.swails@gmail.com',
          py_modules=['lambda_handler'],
          packages=find_packages('.'),
         )
