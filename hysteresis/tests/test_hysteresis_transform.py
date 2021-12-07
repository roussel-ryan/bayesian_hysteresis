import pytest
import torch

from hysteresis.transform import HysteresisTransform


class TestHysteresisTransform:
    def test_hysteresis_transform_init(self):
        train_h = torch.linspace(0, 10)
        train_h = torch.cat((train_h, train_h.flipud()))
        train_m = train_h ** 2

        ht = HysteresisTransform(train_h, train_m, 2)

        # just transform / un-transform h
        assert torch.all(
            torch.isclose(
                ht.transform(train_h)[:100],
                torch.linspace(0, 1)
            )
        )

        assert torch.all(
            torch.isclose(
                ht.untransform(torch.linspace(0, 1.0)),
                train_h[:100]
            )
        )

        # test fitting
        assert torch.all(
            torch.isclose(
                train_m,
                ht.poly_fit(train_h).detach(),
                atol=1e-2
            )
        )

        # test full circle
        test_h = torch.rand(10)
        test_m = torch.rand(10)
        n = ht.transform(test_h, test_m)
        r = ht.untransform(*n)

        for ele1, ele2 in zip((test_h, test_m), r):
            assert torch.all(
                torch.isclose(
                    ele1,
                    ele2,
                    atol=1e-2
                )
            )

        test_h = torch.linspace(0, 100)
        with pytest.raises(RuntimeWarning):
            ht.untransform(test_h)
