from setuptools import setup, find_packages

setup(
    name="wagtail-thumbify",
    version="0.1.4",
    install_requires=["libthumbor", "Pillow"],
    description="Thumbify for Wagtail.",
    author="Andreas Sundström",
    author_email="andreas@ohmy.se",
    url="http://github.com/Oh-My/wagtail-thumbify",
    zip_safe=True,
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Framework :: Django",
    ],
)
