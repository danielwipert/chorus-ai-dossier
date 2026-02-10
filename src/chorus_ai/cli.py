import argparse

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="chorus-ai")
    parser.add_argument("pdf", nargs="?", help="Path to input PDF")
    parser.add_argument("--config", help="Path to config JSON")
    args = parser.parse_args(argv)

    print("chorus-ai is installed and runnable.")
    print(f"pdf={args.pdf} config={args.config}")
    return 0
