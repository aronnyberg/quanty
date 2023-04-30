import setuptools 

#1. Create a folder for your private code library
#2. Create an __init__ py file inside the code library
#3. Create a setup file outside the private code library
#4. Now you can add code files inside the quantlib folder and use it as a package like any other! (pip install using developement mode) >> python3 -m pip install -e.

setuptools.setup(
    name="quant",
    version="0.1",
    description="code lib by HangukQuant, Aron",
    url="#",
    author="HangukQuant, Aron",
    install_requires=["opencv-python", "pandas", "oandapyV20", "seaborn", "requests", "bs4", "termcolor", "TA-Lib", "scipy", "openpyxl"],
    author_email="",
    packages=setuptools.find_packages(),
    zip_safe=False
) #do go and read what these parameters mean!

#you now have a code library!