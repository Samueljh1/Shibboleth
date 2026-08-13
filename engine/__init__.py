"""Entropy engine — Task C. ⭐

    from engine.engine import EntropyEngine
    from engine.llm import OpenRouterLlm

`engine.infogain` holds the pure maths (entropy, expected information gain,
Bayes update, grading) and imports nothing from the rest of the package, so it
can be imported and tested on its own.

Deliberately no re-exports here: `app/main.py` imports the concrete modules,
and keeping this file empty means importing `engine.infogain` never drags in
`requests` or the store.
"""
