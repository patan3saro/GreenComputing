import os
import random
import numpy as np


def set_global_seed(seed: int):
    """Imposta **tutte** le sorgenti di random e restituisce
    un `numpy.random.Generator` da usare ovunque servano numeri casuali.
    """
    random.seed(seed)            # modulo standard
    np.random.seed(seed)         # legacy RandomState
    os.environ["PYTHONHASHSEED"] = str(seed)
    return np.random.default_rng(seed)  # nuovo generatore deterministico
