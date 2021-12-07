import torch
from torch.nn import Module, Parameter
from torch import Tensor
from typing import Dict, Callable
from .meshing import create_triangle_mesh, default_mesh_size
from .states import get_states, predict_batched_state
from .transform import HysteresisTransform


class BaseHysteresis(Module):
    _mode = 'train'

    def __init__(
            self,
            train_h: Tensor = None,
            train_m: Tensor = None,
            trainable: bool = True,
            tkwargs: Dict = None,
            mesh_scale: float = 1.0,
            mesh_density_function: Callable = None,
            polynomial_degree: int = 1,
            temp: float = 1e-2,
    ):
        super(BaseHysteresis, self).__init__()

        self.tkwargs = tkwargs or {}
        self.tkwargs.update({"dtype": torch.double, "device": "cpu"})

        # generate mesh grid on 2D normalized domain [[0,1],[0,1]]
        self.temp = temp
        self.mesh_scale = mesh_scale
        self.mesh_points = torch.tensor(
            create_triangle_mesh(mesh_scale, mesh_density_function), **self.tkwargs
        )

        # initialize trainable parameters
        density = torch.zeros(len(self.mesh_points))
        offset = torch.zeros(1)
        scale = torch.ones(1)
        slope = torch.zeros(1)
        param_vals = [density, offset, scale, slope]
        param_names = [
            "_raw_hysterion_density",
            "offset",
            "scale",
            "slope"
        ]

        self.trainable = trainable
        for param_name, param_val in zip(param_names, param_vals):
            if self.trainable:
                self.register_parameter(param_name, Parameter(param_val))

            else:
                self.register_buffer(param_name, Parameter(param_val))

        # if provided create normalization transform and set magnetization history
        self.polynomial_degree = polynomial_degree
        self.set_history(train_h, train_m)

    def set_history(self, history_h, history_m, retrain_normalization=True):
        """ set historical state values and recalculate hysterion states"""
        if retrain_normalization:
            self.transformer = HysteresisTransform(
                history_h, history_m,
                self.polynomial_degree
            )

        _history_h, _history_m = self.transformer.transform(history_h, history_m)
        self.register_buffer('_history_h', _history_h)
        self.register_buffer('_history_m', _history_m)

        # recalculate states
        _states = get_states(self._history_h, self.mesh_points, temp=self.temp)
        self.register_buffer('_states', _states)

    @property
    def hysterion_density(self):
        return torch.nn.Softplus()(self._raw_hysterion_density)

    @hysterion_density.setter
    def hysterion_density(self, value: Tensor):
        self._raw_hysterion_density = Parameter(
            torch.log(torch.exp(value.clone()) - 1).to(**self.tkwargs)
        )

    def _predict_normalized_magnetization(self, states, h):
        m = torch.sum(self.hysterion_density * states, dim=-1) / torch.sum(
            self.hysterion_density
        )
        return self.scale * m + self.offset + h * self.slope

    def get_negative_saturation(self):
        return self.transformer.untransform(torch.zeros(1), -self.scale +
                                            self.offset)[1]

    def forward(self, x: Tensor, **kwargs):

        return_norm = kwargs.get('return_norm', False)
        if self._mode == 'train':
            assert torch.all(torch.isclose(
                x,
                self.transformer.untransform(self._history_h)[0]
            )), "must train on history fields"
            states = self._states
            return self._predict_normalized_magnetization(states, self._history_h)

        elif self._mode == 'future':
            norm_h, _ = self.transformer.transform(x)
            states = get_states(
                norm_h,
                self.mesh_points,
                current_state=self._states[-1],
                current_field=self._history_h[-1],
                tkwargs=self.tkwargs
            )

            if return_norm:
                return self._predict_normalized_magnetization(
                    states, norm_h
                )
            else:
                return self.transformer.untransform(
                    norm_h,
                    self._predict_normalized_magnetization(
                        states, norm_h
                    )
                )[1]

        elif self._mode == 'next':
            if x.shape[1:] != torch.Size([1, 1]):
                raise ValueError(f'shape of x must be [-1, 1, 1] for next mode, '
                                 'current shape is {x.shape}')
            norm_h, _ = self.transformer.transform(x)

            states = predict_batched_state(
                norm_h,
                self.mesh_points,
                current_state=self._states[-1],
                current_field=self._history_h[-1],
            )

            norm_h = norm_h.reshape(-1, states.shape[-2])
            norm_m = self._predict_normalized_magnetization(
                    states, norm_h
                ).reshape(-1, 1, 1)
            if return_norm:
                return norm_m
            else:
                return self.transformer.untransform(
                    norm_h,
                    norm_m
                )[1]
        else:
            raise ValueError(f'mode:`{self._mode}` not accepted')

    @property
    def history_h(self):
        return self.transformer.untransform(self._history_h)

    @property
    def history_m(self):
        _, m = self.transformer.untransform(self._history_h, self._history_m)
        return m

    def train(self, **kwargs):
        self._mode = 'train'

    def future(self):
        self._mode = 'future'

    def next(self):
        self._mode = 'next'
