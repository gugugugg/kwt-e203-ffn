"""Independent float32 NumPy encoder for checking exported hardware boundaries."""

import numpy as np
from scipy.special import erf


def layer_norm(x, gamma, beta):
    mean = np.mean(x, axis=-1, keepdims=True)
    variance = np.mean(np.square(x - mean), axis=-1, keepdims=True)
    return (x - mean) / np.sqrt(variance + np.float32(1e-6)) * gamma + beta


def encoder(x, parameters):
    """Accept (99,64), return (12,99,64) and 12 logits; dense kernels are [in,out]."""
    outputs = []
    for i in range(12):
        prefix = f'encoder.{i:02d}.'
        p = {name[len(prefix):]: value for name, value in parameters.items() if name.startswith(prefix)}
        q, k, v = [x @ p[f'attention.{name}.kernel'] for name in ('q', 'k', 'v')]
        scores = (q @ k.T) * np.float32(0.125)
        probabilities = np.exp(scores - np.max(scores, axis=-1, keepdims=True))
        probabilities /= np.sum(probabilities, axis=-1, keepdims=True)
        attention = (probabilities @ v) @ p['attention.output.kernel'] + p['attention.output.bias']
        y = layer_norm(x + attention, p['norm1.gamma'], p['norm1.beta'])
        fc1 = y @ p['ffn.fc1.kernel'] + p['ffn.fc1.bias']
        gelu = np.float32(0.5) * fc1 * (np.float32(1.0) + erf(fc1 / np.sqrt(np.float32(2.0))))
        fc2 = gelu @ p['ffn.fc2.kernel'] + p['ffn.fc2.bias']
        x = layer_norm(y + fc2, p['norm2.gamma'], p['norm2.beta'])
        outputs.append(x)
    return np.stack(outputs), x[0] @ parameters['classifier.kernel'] + parameters['classifier.bias']
