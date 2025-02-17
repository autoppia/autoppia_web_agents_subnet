import json
import re
from pathlib import Path


# TODO: CHECK IF IT IS USEFUL AND PROBABLY WE HAVE TO MOVE IT TO LLM MODULE
class PromptLLMTemplate:
    def __init__(self, template: str, variables: list = None, values: dict = None, schema: dict = None):
        """
        Initializes the PromptLLMTemplate.

        Args:
            template (str): The text template containing variables in the format ${variable}.
            variables (list): Optional list of variables present in the template.
            values (dict): Optional dictionary of values to replace the variables.
            schema (dict): Optional JSON schema for validation of values.
        """
        self.template = template
        self.variables = variables or []
        self.values = values or {}
        self.schema = schema
        self.variables_replaced = self.values.copy()
        self.current_prompt = self.template
        self.replaced = False

        if self.values:
            self.current_prompt = self.replace(self.values)
            self.replaced = True

    def replace(self, values: dict = None) -> str:
        if values is None:
            return self.current_prompt

        # if values:
        # Add the variables to replaces to the global variables replaced to keep track of which have been replaced
        self.variables_replaced = self.variables_replaced.update(values) if self.variables_replaced else self.variables_replaced
        self.values = self.values.update(values) if self.values else self.values

        # Find all occurrences of the form ${variable}
        for match in re.findall(r"\${(.*?)}", self.current_prompt):
            # Only replace if the key exists in the dictionary
            if match in values:
                value = values[match]
                self.current_prompt = self.current_prompt.replace(f"${{{match}}}", str(value))

        return self.current_prompt

    def get_schema(self):
        return {"response_format": {"type": "json_object", "schema": self.schema}}

    @staticmethod
    def clean_prompt(prompt):
        # Replace all 'NONE' values with an empty string
        cleaned_prompt = prompt.replace("NONE", "")
        cleaned_prompt = cleaned_prompt.replace("\n", "")
        cleaned_prompt = re.sub(r"\${(.*?)}", "", cleaned_prompt)
        return cleaned_prompt

    @classmethod
    def get_instance_from_file(cls, file_path: str, schema_path: str, values: dict = None):
        """Create an instance of PromptLLMTemplate from a file."""
        schema = None
        base_dir = Path(__file__).resolve().parents[3]
        try:
            prompt_path = base_dir / file_path
            with prompt_path.open("r", encoding="utf-8") as file:
                system_prompt_text = file.read()

            if schema_path:
                schema_path_full = base_dir / schema_path
                with schema_path_full.open("r", encoding="utf-8") as schema_file:
                    schema = json.load(schema_file)

            return cls(system_prompt_text, values=values, schema=schema)
        except FileNotFoundError as e:
            raise FileNotFoundError(f"File not found: {e.filename}")
        except json.JSONDecodeError as e:
            raise Exception(f"Error parsing JSON schema: {e.msg}")
        except Exception as e:
            raise Exception(f"An error occurred: {e}")
