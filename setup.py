from setuptools import setup
import os.path

HERE = os.path.abspath(os.path.dirname(__file__))


def read(*parts):
    with open(os.path.join(HERE, *parts)) as f:
        return f.read()


setup(
    name="mypy-runner",
    version="0.3.0",
    author="Chad Dombrova",
    description="Run mypy with options to filter errors and colorize output",
    long_description=read("README.rst"),
    license="MIT",
    keywords=["mypy", "typing", "pep484", "annotations"],
    url="https://github.com/chadrik/mypy-runner",
    py_modules=['mypyrun'],
    entry_points={
        'console_scripts': ['mypyrun=mypyrun:main'],
    },
    install_requires=['configparser', 'colorama'],
    extras_require={
        "tests": [
            "coverage",
            "pytest==5.2.0",
            "tox==3.14.0",
            "mypy==0.730",
        ],
    },
    classifiers=[
        # How mature is this project? Common values are
        #   3 - Alpha
        #   4 - Beta
        #   5 - Production/Stable
        'Development Status :: 4 - Beta',

        # Indicate who your project is intended for
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Build Tools',

        # Pick your license as you wish (should match "license" above)
        'License :: OSI Approved :: MIT License',

        # Specify the Python versions you support here. In particular, ensure
        # that you indicate whether you support Python 2, Python 3 or both.
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
    ],
)
