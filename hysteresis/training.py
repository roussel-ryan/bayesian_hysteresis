import pyro
import torch
from pyro.infer import SVI, Trace_ELBO
from pyro.infer.autoguide import AutoMultivariateNormal, AutoDelta


def train_torch(model, magnetization, n_steps, lr=0.1):
    def loss_fn(m, m_pred):
        return torch.sum((m - m_pred) ** 2)

    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    loss_track = []
    for i in range(n_steps):
        optimizer.zero_grad()
        output = model.predict_magnetization()
        loss = loss_fn(magnetization, output)
        loss.backward(retain_graph=True)

        loss_track += [loss]
        optimizer.step()
        if i % 100 == 0:
            print(i)

    return torch.tensor(loss_track)


def train_bayes(h, m, model, num_steps, guide=None, initial_lr=0.001, gamma=0.1):
    guide = guide or AutoMultivariateNormal(model)

    lrd = gamma ** (1 / num_steps)
    optim = pyro.optim.ClippedAdam({"lr": initial_lr, "lrd": lrd})
    svi = SVI(model, guide, optim, loss=Trace_ELBO())

    pyro.clear_param_store()
    loss_trace = []
    for j in range(num_steps):
        # calculate the loss and take a gradient step
        loss = svi.step(h, m)
        loss_trace += [loss]
        if j % 100 == 0:
            print("[iteration %04d] loss: %.4f" % (j + 1, loss))

    return guide, torch.tensor(loss_trace)


def map_bayes(h, m, model, num_steps, initial_lr=0.001, gamma=0.1):
    """maximum a posteriori point estimation of parameters"""
    guide = AutoDelta(model)
    return train_bayes(h, m, model, num_steps, guide, initial_lr, gamma)


def mle_bayes(h, m, model, num_steps, initial_lr=0.001, gamma=0.1):
    def empty_guide(X, Y):
        pass

    return train_bayes(h, m, model, num_steps, empty_guide, initial_lr, gamma)