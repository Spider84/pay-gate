import os
from setuptools import setup

# Utility function to read the README file.
# Used for the long_description.  It's nice, because now 1) we have a top level
# README file and 2) it's easier to type in the README file than to put a raw
# string in below ...
def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup(
    name="pay_gate",
    version="1.0.4",
    author="Alexey Belyaev",
    author_email="spider@spder.vc",
    description=("Демон управления парковокй по оплате."),
    packages=['pay_gate'],
    long_description=read('README'),
    long_description_content_type="text/markdown",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Console",
        "Topic :: Daemons"
    ],
    python_requires='>=3.7',
    install_requires=[
        'python-telegram-bot',
        'ssd1306',
        'OPi.GPIO',
        'pillow'
    ],
    # If there are data files included in your packages that need to be
    # installed, specify them here.  If using Python 2.6 or less, then these
    # have to be included in MANIFEST.in as well.
    package_data={
        'pay_gate': ['fonts/*.ttf', 'translations/*']
    },
    entry_points={
        'console_scripts': [
            'pay_gate = pay_gate.__main__:main',
        ]
    }
)
