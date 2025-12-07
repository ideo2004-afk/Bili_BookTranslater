#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get the directory where the script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo -e "${GREEN}=== Bilingual Book Maker Installer ===${NC}"

# Function to check python version
check_python_version() {
    local py_bin=$1
    local version=$($py_bin -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    local major=$(echo $version | cut -d. -f1)
    local minor=$(echo $version | cut -d. -f2)
    
    if [ "$major" -eq 3 ] && [ "$minor" -ge 13 ]; then
        return 1 # Too new (>= 3.13)
    fi
    return 0 # OK
}

# Find a suitable Python interpreter
PYTHON_BIN=""
# Preferred versions in order (3.11 is most stable for our deps, 3.10/3.12 are also good)
PREFERRED_VERSIONS=("python3.11" "python3.10" "python3.12" "python3.9" "python3")

echo -e "${YELLOW}Searching for a compatible Python version (3.8 - 3.12)...${NC}"

for ver in "${PREFERRED_VERSIONS[@]}"; do
    # Check standard paths
    for path in "/opt/homebrew/bin/$ver" "/usr/local/bin/$ver" "/usr/bin/$ver" "$(command -v $ver)"; do
        if [ -x "$path" ]; then
            if check_python_version "$path"; then
                PYTHON_BIN="$path"
                echo -e "${GREEN}Found compatible Python: $PYTHON_BIN${NC}"
                break 2
            fi
        fi
    done
done

if [ -z "$PYTHON_BIN" ]; then
    echo -e "${YELLOW}Warning: No optimal Python version found. Checking default python3...${NC}"
    if command -v python3 &> /dev/null; then
        PYTHON_BIN=$(command -v python3)
        echo -e "${YELLOW}Using default: $PYTHON_BIN${NC}"
        # Warn if it looks too new, but try anyway
        if ! check_python_version "$PYTHON_BIN"; then
             echo -e "${YELLOW}CAUTION: Your Python version appears to be 3.13 or newer.${NC}"
             echo -e "${YELLOW}Some dependencies (like PySide6/grpcio) may fail to install.${NC}"
             echo -e "${YELLOW}If installation fails, please install Python 3.11: 'brew install python@3.11'${NC}"
             echo -e "${YELLOW}Waiting 3 seconds before continuing...${NC}"
             sleep 3
        fi
    else
        echo "Error: Python 3 is not installed."
        exit 1
    fi
fi

# Create Virtual Environment
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating virtual environment using $PYTHON_BIN...${NC}"
    "$PYTHON_BIN" -m venv venv
else
    echo -e "${GREEN}Virtual environment already exists.${NC}"
fi

# Activate venv
source venv/bin/activate

# Upgrade pip
echo -e "${YELLOW}Upgrading pip...${NC}"
pip install --upgrade pip

# Install Dependencies
if [ -f "requirements.txt" ]; then
    echo -e "${YELLOW}Installing dependencies from requirements.txt...${NC}"
    pip install -r requirements.txt
else
    echo -e "${YELLOW}requirements.txt not found. Installing core dependencies...${NC}"
    pip install openai google-generativeai beautifulsoup4 tiktoken ebooklib rich tqdm
fi

# Install GUI dependencies specifically
echo -e "${YELLOW}Installing GUI dependencies (PySide6)...${NC}"
pip install PySide6

echo -e "${GREEN}=== Installation Complete! ===${NC}"
echo -e "You can now run the GUI using: ${YELLOW}./run_gui.command${NC}"
echo -e "Or run the CLI using: ${YELLOW}./venv/bin/python make_book.py${NC}"
