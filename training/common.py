"""Shared by training and prediction: how a command becomes a prompt."""

def prompt_for(command: str) -> str:
    # Training examples are "<prompt> <teacher reply>"; at inference the model continues after the prompt.
    return f"Command: {command}\nJSON:"
