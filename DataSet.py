import pandas as pd
from scipy.io import arff

class DataSet:

    def __init__(self, source_path, dataset_type, target_class, batch_size, feature_types, name=None):
        # check data format
        if type(source_path) == str:
            self.name = source_path
            source_format = source_path.split(".")[-1]
            if source_format in ("csv", "data"):
                self.data = pd.read_csv(source_path)
            elif source_format == "arff":
                data, meta = arff.loadarff(source_path)
                pd_df = pd.DataFrame(data)
                pd_df[target_class] = pd_df[target_class].astype('int')
                self.data = pd_df
        else:  # already dataframe
            self.data = source_path
            self.name = name

        if dataset_type == "diagnosis_check":  # shuffle data, same shuffle everytime
            self.data = self.data.sample(frac=1, random_state=42).reset_index(drop=True)

        self.dataset_type = dataset_type
        self.features = list(self.data.columns)
        self.features.remove(target_class)
        self.target = target_class
        self.batch_size = batch_size
        self.feature_types = feature_types

if __name__ == '__main__':
    d = DataSet("data/sea.arff", None, "cl")
    print(d.features)
    d = DataSet("data/sea_0123_abrupto_noise_0.2.csv", None, "class")
    print(d.features)
