"""Entry point for the Seesam local terminal assistant."""

from __future__ import annotations

from core.brain import Brain


def main() -> None:
    """Start the terminal chat loop."""
    brain = Brain.from_environment()

    print("Seesam käynnissä. Lopeta komennolla 'exit' tai Ctrl-D.")
    while True:
        try:
            user_input = input("Marko: ").strip()
        except EOFError:
            print()
            break

        if not user_input:
            continue
        if user_input.casefold() in {"exit", "quit", "lopeta"}:
            break

        print(f"Seesam: {brain.respond(user_input)}")


if __name__ == "__main__":
    main()
