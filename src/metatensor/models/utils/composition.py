from typing import List

import rascaline.torch
import torch
from metatensor.torch import Labels, TensorBlock, TensorMap


def calculate_composition_weights(
    datasets: List[torch.utils.data.Dataset], property: str
) -> torch.Tensor:
    """Calculate the composition weights for a dataset.
    For now, it assumes per-structure properties.

    Parameters
    ----------
    dataset: torch.data.utils.Dataset
        Dataset to calculate the composition weights for.

    Returns
    -------
    torch.Tensor
        Composition weights for the dataset.
    """

    # Get the target for each structure in the dataset
    targets = torch.stack(
        [
            sample[1][property].block().values
            for dataset in datasets
            for sample in dataset
        ]
    )

    # Get the composition for each structure in the dataset
    composition_calculator = rascaline.torch.AtomicComposition(per_structure=True)
    composition_features = composition_calculator.compute(
        [sample[0] for dataset in datasets for sample in dataset]
    )
    composition_features = composition_features.keys_to_properties("species_center")
    composition_features = composition_features.block().values

    targets = targets.squeeze(dim=(1, 2))  # remove component and property dimensions

    regularizer = 1e-20

    while regularizer:
        if regularizer > 1e5:
            raise RuntimeError(
                "Failed to solve the linear system to calculate the "
                "composition weights. The dataset is probably too small "
                "or ill-conditioned."
            )
        try:
            solution = torch.linalg.solve(
                composition_features.T @ composition_features
                + regularizer
                * torch.eye(
                    composition_features.shape[1],
                    dtype=composition_features.dtype,
                    device=composition_features.device,
                ),
                composition_features.T @ targets,
            )
            break
        except torch._C._LinAlgError:
            regularizer *= 10.0

    return solution


def apply_composition_contribution(
    atomic_property: TensorMap, composition_weights: torch.Tensor
) -> TensorMap:
    """Apply the composition contribution to an atomic property.

    Parameters
    ----------
    atomic_property: TensorMap
        Atomic property to apply the composition contribution to.
    composition_weights: torch.Tensor
        Composition weights to apply.

    Returns
    -------
    TensorMap
        Atomic property with the composition contribution applied.
    """

    new_keys: List[int] = []
    new_blocks: List[TensorBlock] = []
    for key, block in atomic_property.items():
        atomic_species = int(key.values.item())
        new_keys.append(atomic_species)
        new_values = block.values + composition_weights[atomic_species]
        new_blocks.append(
            TensorBlock(
                values=new_values,
                samples=block.samples,
                components=block.components,
                properties=block.properties,
            )
        )

    new_keys_labels = Labels(
        names=["species_center"],
        values=torch.tensor(new_keys, device=new_blocks[0].values.device).reshape(
            -1, 1
        ),
    )

    return TensorMap(keys=new_keys_labels, blocks=new_blocks)
