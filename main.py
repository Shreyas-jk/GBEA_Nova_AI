#!/usr/bin/env python3


from __future__ import annotations

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.text import Text

from config import AWS_REGION, MODEL_ID, MAX_TOKENS, TEMPERATURE, ORCHESTRATOR_SYSTEM_PROMPT


console = Console()


def _build_orchestrator():
    """Create the orchestrator agent with all tools."""
    from strands import Agent
    from strands.models import BedrockModel
    from tools import (
        intake_interview,
        check_eligibility,
        create_action_plan,
        search_benefits_kb,
        analyze_document,
        suggest_followup,
    )

    try:
        model = BedrockModel(
            model_id=MODEL_ID,
            region_name=AWS_REGION,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            streaming=True,
        )
    except Exception as e:
        console.print(
            Panel(
                f"[bold red]Failed to initialize Bedrock model.[/bold red]\n\n"
                f"Error: {e}\n\n"
                f"Make sure you have:\n"
                f"  1. AWS credentials configured (aws configure)\n"
                f"  2. Access to Amazon Nova 2 Lite enabled in the Bedrock console\n"
                f"  3. The correct AWS region set (current: {AWS_REGION})\n\n"
                f"Set environment variables:\n"
                f"  export AWS_REGION=us-east-1\n"
                f"  export MODEL_ID=global.amazon.nova-2-lite-v1:0",
                title="Configuration Error",
                border_style="red",
            )
        )
        sys.exit(1)

    agent = Agent(
        model=model,
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        tools=[intake_interview, check_eligibility, create_action_plan, search_benefits_kb, analyze_document, suggest_followup],
    )
    return agent


def _print_welcome():
    console.print()
    console.print(
        Panel(
            "[bold cyan]Welcome to BenefitsNavigator[/bold cyan]\n\n"
            "I'm an AI assistant that helps you discover government benefits\n"
            "you may be eligible for — including food assistance, healthcare,\n"
            "housing, tax credits, and more.\n\n"
            "[dim]Tell me about your situation and I'll help identify programs\n"
            "you might qualify for and create an action plan to apply.[/dim]\n\n"
            "[yellow]Disclaimer:[/yellow] This tool provides informational guidance only.\n"
            "Final eligibility is determined by the administering agency.\n\n"
            "[dim]Type 'quit', 'exit', or 'q' to leave.[/dim]",
            title="BenefitsNavigator",
            subtitle="Powered by Amazon Nova 2 Lite on AWS Bedrock",
            border_style="cyan",
        )
    )
    console.print()


def _run_chat_loop(agent):
    """Interactive chat loop."""
    _print_welcome()

    while True:
        try:
            user_input = console.input("[bold green]> [/bold green]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            console.print("[dim]Goodbye! Remember to check back if your situation changes.[/dim]")
            break

        try:
            console.print()
            with console.status("[cyan]Thinking...[/cyan]", spinner="dots"):
                response = agent(user_input)

            response_text = str(response)
            console.print(
                Panel(
                    Markdown(response_text),
                    title="BenefitsNavigator",
                    border_style="blue",
                    padding=(1, 2),
                )
            )
            console.print()

        except Exception as e:
            error_msg = str(e)
            if "AccessDeniedException" in error_msg:
                console.print(
                    Panel(
                        "[red]Access denied to the Bedrock model.[/red]\n\n"
                        "Please enable Amazon Nova 2 Lite in the AWS Bedrock console:\n"
                        "  1. Go to the Amazon Bedrock console\n"
                        "  2. Navigate to Model access\n"
                        "  3. Enable 'Amazon Nova 2 Lite'\n"
                        f"  4. Make sure you're in the {AWS_REGION} region",
                        title="Access Error",
                        border_style="red",
                    )
                )
            elif "ExpiredTokenException" in error_msg or "credentials" in error_msg.lower():
                console.print(
                    Panel(
                        "[red]AWS credentials expired or missing.[/red]\n\n"
                        "Please run: aws configure\n"
                        "Or set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY",
                        title="Credentials Error",
                        border_style="red",
                    )
                )
            else:
                console.print(
                    Panel(
                        f"[red]An error occurred:[/red] {error_msg}",
                        title="Error",
                        border_style="red",
                    )
                )
            console.print()


def _run_single_query(agent, query: str):
    """Run a single query and exit."""
    try:
        response = agent(query)
        console.print(
            Panel(
                Markdown(str(response)),
                title="BenefitsNavigator",
                border_style="blue",
                padding=(1, 2),
            )
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="BenefitsNavigator — discover government benefits you may qualify for."
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Run a single query instead of interactive mode.",
    )
    args = parser.parse_args()

    agent = _build_orchestrator()

    if args.query:
        _run_single_query(agent, args.query)
    else:
        _run_chat_loop(agent)


if __name__ == "__main__":
    main()
