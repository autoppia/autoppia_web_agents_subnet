import tiktoken


# TODO: REVISAR SI PODEMOS QUITAR ESTA DEPNDENCIA
class OpenAIUtilsMixin:
    @staticmethod
    def num_tokens_from_string(string: str, model="gpt-3.5-turbo-0613", disallowed_special=True) -> int:
        """Returns the number of tokens in a text string."""
        encoding = tiktoken.encoding_for_model(model)
        if disallowed_special:
            num_tokens = len(encoding.encode(string, disallowed_special=()))
        else:
            num_tokens = len(encoding.encode(string))

        return num_tokens
