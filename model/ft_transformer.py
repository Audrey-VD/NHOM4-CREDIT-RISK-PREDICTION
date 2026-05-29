import torch
import torch.nn as nn
import numpy as np

class FeatureTokenizer(nn.Module):
    def __init__(self, n_features, d_token):
        super().__init__()
        self.weight = nn.Parameter(torch.empty(n_features, d_token))
        self.bias = nn.Parameter(torch.zeros(n_features, d_token))
        nn.init.kaiming_uniform_(self.weight, a=np.sqrt(5))
        self.cls_token = nn.Parameter(torch.zeros(1, 1, d_token))

    def forward(self, x):
        tokens = x.unsqueeze(-1) * self.weight + self.bias
        cls = self.cls_token.expand(x.size(0), -1, -1)
        return torch.cat([cls, tokens], dim=1)


class FTTransformer(nn.Module):
    def __init__(self, n_features, d_token=64, n_heads=8, n_layers=3, dropout=0.1):
        super().__init__()
        assert d_token % n_heads == 0
        self.tokenizer = FeatureTokenizer(n_features, d_token)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_token, nhead=n_heads,
            dim_feedforward=d_token * 4,
            dropout=dropout, batch_first=True, norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.head = nn.Sequential(nn.LayerNorm(d_token), nn.ReLU(), nn.Linear(d_token, 1))

    def forward(self, x):
        out = self.transformer(self.tokenizer(x))
        return self.head(out[:, 0, :])