from setuptools import setup, find_packages

setup(
    name="on-track-erp",
    version="1.0.0",
    packages=find_packages(where="."),
    package_dir={"": "."},
)
