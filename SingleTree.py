import copy
from datetime import datetime

import numpy as np
from DataSet import DataSet
from SHAP import applySHAP
from buildModel import build_model, map_tree
from sklearn import metrics
from SFL import *
from updateModel import *

# all_datasets_single_tree = [
#     DataSet("data/hyperplane1.arff", "abrupt", "output", 1000, ["numeric"]*10),
#     DataSet("data/hyperplane2.arff", "abrupt", "output", 1000, ["numeric"]*10),
#     DataSet("data/hyperplane3.arff", "abrupt", "output", 1000, ["numeric"]*10),
#     DataSet("data/hyperplane4.arff", "abrupt", "output", 1000, ["numeric"]*10),
#     DataSet("data/hyperplane5.arff", "abrupt", "output", 1000, ["numeric"]*10),
#     DataSet("data/hyperplane6.arff", "abrupt", "output", 1000, ["numeric"]*10),
#     DataSet("data/hyperplane7.arff", "abrupt", "output", 1000, ["numeric"]*10),
#     DataSet("data/hyperplane8.arff", "abrupt", "output", 1000, ["numeric"]*10),
#     DataSet("data/hyperplane9.arff", "abrupt", "output", 1000, ["numeric"]*10),
#     DataSet("data/rt_2563789698568873_abrupto.csv", "abrupt", "class", 10000, ["numeric"]*2),
#     DataSet("data/sea_0123_abrupto_noise_0.2.csv", "abrupt", "class", 10000, ["numeric"]*3),
#     DataSet("data/mixed_0101_abrupto.csv", "abrupt", "class", 10000, ["binary"]*2+["numeric"]*2),
#     DataSet("data/mixed_1010_abrupto.csv", "abrupt", "class", 10000, ["binary"]*2+["numeric"]*2),
#     DataSet("data/stagger_2102_abrupto.csv", "abrupt", "class", 10000, ["categorical"]*4)
# ]

# all_datasets_single_tree = [
#     DataSet("data/real/iris.data", "diagnosis_check", "class", 100, ["numeric"]*4, name="iris", to_shuffle=True)
# ]

SIZE = -1
NEW_DATA_SIZE = -1

def feature_diff_after_concept_drift(data_set, drift_size, new_data_size):
    diff = dict()
    i = 0
    for feature in data_set.features:
        before = data_set.data[feature].iloc[0:drift_size]
        before_avg = before.mean()
        after = data_set.data[feature].iloc[drift_size: drift_size + new_data_size]
        after_avg = after.mean()
        diff[i] = after_avg - before_avg
        i += 1
    return diff

def diagnose_SHAP(model, dataset, new_data, prediction):
    # diagnose model - SHAP
    shap_values = applySHAP(dataset.features, new_data, model)
    new_data_y = new_data[dataset.target]
    build_SFL_matrix_SHAP(dataset.features, shap_values, prediction, new_data_y, dataset.name)
    diagnosis = get_diagnosis()
    print("diagnosis: {}".format(diagnosis))
    # TODO: rate diagnosis
    first_diagnosis = diagnosis[0].diagnosis
    return first_diagnosis

def best_diagnosis(diagnoses, probabilities, spectra, error_vector, best_method="first"):
    print("diagnoses: {}".format(diagnoses))
    print("probabilities: {}".format(probabilities))
    if best_method == "first":
        best = diagnoses[0]
        if type(best == int):
            best = [best]
    return best

def barinel_single_node(diagnoses, probabilities, n_nodes):
    score = np.zeros(n_nodes)
    for i in range(len(diagnoses)):
        prob = probabilities[i]
        d = diagnoses[i]
        score[d] += prob
    d_order = np.argsort(-score)
    probabilities = score[d_order]
    diagnoses = list(map(int, d_order))
    return diagnoses, probabilities


def fix_SHAP(model, diagnosis, dataset):
    # fix model - SHAP
    features_diff = feature_diff_after_concept_drift(dataset, SIZE, NEW_DATA_SIZE)
    nodes, thresholds = find_nodes_threshold_from_diagnosis(model, diagnosis, features_diff)
    model_to_fix = copy.deepcopy(model)
    fixed_model = change_tree_threshold(model_to_fix, nodes, thresholds)
    return fixed_model

def diagnose_Nodes(model, new_data, model_rep):
    nodes = model.tree_.node_count
    print("number of nodes: {}".format(nodes))
    BAD_SAMPLES, spectra, error_vector, conflicts = get_SFL_for_diagnosis_nodes(model, new_data, model_rep)
    priors = get_prior_probs(model_rep, nodes)
    diagnoses, probabilities = get_diagnosis_barinel(spectra, error_vector, priors)
    return (diagnoses, probabilities), BAD_SAMPLES, spectra, error_vector, conflicts

def diagnose_single_node(model, new_data, model_rep):
    nodes = model.tree_.node_count
    BAD_SAMPLES, spectra, error_vector, conflicts = get_SFL_for_diagnosis_nodes(model, new_data, model_rep)
    priors = get_prior_probs(model_rep, nodes)
    diagnoses, probabilities = get_diagnosis_single_fault(spectra, error_vector, "cosine", priors=priors)
    return (diagnoses, probabilities), BAD_SAMPLES, spectra, error_vector, conflicts

def fix_nodes_binary(model, diagnosis):
    # fix model - Nodes, change selection (right <--> left)
    model_to_fix = copy.deepcopy(model)
    fixed_model = change_tree_selection(model_to_fix, diagnosis)
    return fixed_model

def fix_nodes_numeric(model, diagnosis, dataset):
    # fix model - Nodes, change node's thresholds (feature mean before & after drift)
    model_to_fix = copy.deepcopy(model)
    features_diff = feature_diff_after_concept_drift(dataset, SIZE, NEW_DATA_SIZE)
    fixed_model = change_nodes_threshold(model_to_fix, diagnosis, features_diff)
    return fixed_model

def fix_nodes_by_type(model, diagnosis, dataset, diff_type="all", tree_rep=None):
    # fix model - Nodes, change selection or threshold
    model_to_fix = copy.deepcopy(model)
    features_diff = feature_diff_after_concept_drift(dataset, SIZE, NEW_DATA_SIZE)
    fixed_model = change_nodes_by_type(model_to_fix, diagnosis, dataset.feature_types, features_diff, diff_type,tree_rep,dataset)
    return fixed_model

def run_single_tree_experiment(dataset, model=None, check_diagnosis=False, faulty_nodes=[]):
    result = {}
    global SIZE, NEW_DATA_SIZE
    SIZE = dataset.before_size
    result["drift size"] = SIZE
    NEW_DATA_SIZE = dataset.after_size
    # NEW_DATA_SIZE = 100
    result["#samples used"] = NEW_DATA_SIZE
    result["feature types"] = dataset.feature_types

    if not model: # create a model
        model = build_model(dataset.data.iloc[0:int(0.9*SIZE)], dataset.features, dataset.target)
    model_rep = map_tree(model)

    # check model accuracy on data before the drift
    test_data = dataset.data.iloc[int(0.9*SIZE): SIZE]
    test_data_x = test_data[dataset.features]
    prediction = model.predict(test_data_x)
    test_data_y = test_data[dataset.target]
    accuracy = metrics.accuracy_score(test_data_y, prediction)
    print("Accuracy of original model on data BEFORE concept drift:", accuracy)
    result["accuracy original model BEFORE drift"] = accuracy

    result["number of nodes"] = model.tree_.node_count
    result["tree size"] = len(model_rep)
    # check model accuracy on data after concept drift
    new_data = dataset.data.iloc[SIZE: SIZE + NEW_DATA_SIZE]
    new_data_x = new_data[dataset.features]
    prediction = model.predict(new_data_x)
    new_data_y = new_data[dataset.target]
    accuracy = metrics.accuracy_score(new_data_y, prediction)
    print("Accuracy of original model on data AFTER concept drift:", accuracy)
    result["accuracy original model AFTER drift"] = accuracy

    #print("TREE:")
    #print_tree_rules(model, dataset.features)

    # RUN ALGORITHM
    samples = (new_data_x, prediction, new_data_y)
    time1 = datetime.now()
    (diagnoses, probabilities), BAD_SAMPLES, spectra, error_vector, conflicts = diagnose_Nodes(model, samples, model_rep)
    diagnoses, probabilities = barinel_single_node(diagnoses,probabilities,model.tree_.node_count)
    #(diagnoses, probabilities), BAD_SAMPLES, spectra, error_vector, conflicts = diagnose_single_node(model, samples, model_rep)
    diagnosis = best_diagnosis(diagnoses, probabilities, spectra, error_vector)
    time2 = datetime.now()
    result["diagnosis time"] = time2 - time1
    result["diagnoses list"] = diagnoses
    result["probabilities"] = probabilities.tolist()
    result["# of diagnoses"] = len(diagnoses)
    result["chosen diagnosis"] = diagnosis
    result["diagnosis cardinality"] = len(diagnosis)
    result["conflicts"] = conflicts
    print(f"best diagnosis: {diagnosis}")
    time1 = datetime.now()
    fixed_model = fix_nodes_by_type(model, diagnosis, dataset)
    time2 = datetime.now()
    result["fixing time"] = time2 - time1

    # print("FIXED TREE:")
    # print_tree_rules(fixed_model, dataset.features)

    # run algorithm - SHAP
    # diagnosis = diagnose_SHAP(model, dataset, new_data)
    # fixed_model = fix_SHAP(model, diagnosis, dataset)

    print("--- new data accuracy ---")
    print("Accuracy of original model on data after concept drift:", accuracy)

    prediction = fixed_model.predict(new_data_x)
    accuracy = metrics.accuracy_score(new_data_y, prediction)
    print("Accuracy of Fixed model on data after concept drift:", accuracy)
    result["accuracy FIXED model AFTER drift"] = accuracy

    # TEST performances
    print("--- test data accuracy ---")
    test_set = dataset.data.iloc[SIZE + NEW_DATA_SIZE: -1]
    test_set_x = test_set[dataset.features]
    test_set_y = test_set[dataset.target]
    result["test set size"] = len(test_set)

    # check original model on the new data
    prediction1 = model.predict(test_set_x)
    accuracy = metrics.accuracy_score(test_set_y, prediction1)
    print("Accuracy of the Original model on test data:", accuracy)
    result["accuracy original model - test data"] = accuracy

    # train a new model with data before and after drift
    time1 = datetime.now()
    model_all = build_model(dataset.data.iloc[0:SIZE + NEW_DATA_SIZE], dataset.features, dataset.target, to_split=True)
    time2 = datetime.now()
    result["new model all time"] = time2 - time1
    prediction2 = model_all.predict(test_set_x)
    accuracy = metrics.accuracy_score(test_set_y, prediction2)
    print("Accuracy of a New model (before & after) on test data:", accuracy)
    result["accuracy New model (before & after) model - test data"] = accuracy

    # train a new model on data after drift
    time1 = datetime.now()
    model_after = build_model(new_data, dataset.features, dataset.target, to_split=True)
    time2 = datetime.now()
    result["new model after time"] = time2 - time1
    prediction4 = model_after.predict(test_set_x)
    accuracy = metrics.accuracy_score(test_set_y, prediction4)
    print("Accuracy of a New model (only after) on test data:", accuracy)
    result["accuracy New model (only after) model - test data"] = accuracy

    # check the fixed model
    prediction3 = fixed_model.predict(test_set_x)
    accuracy = metrics.accuracy_score(test_set_y, prediction3)
    print("Accuracy of Fixed model on test data:", accuracy)
    result["accuracy FIXED model - test data"] = accuracy

    print("--- misclassified (new) data accuracy ---")
    bad_samples_indexes = np.array(BAD_SAMPLES) + SIZE
    bad_samples = dataset.data.iloc[bad_samples_indexes]
    print(f"number of bad samples: {len(bad_samples)}")
    result["number of bad samples"] = len(bad_samples)
    bad_samples_x = bad_samples[dataset.features]
    prediction_bad = model.predict(bad_samples_x)
    bad_samples_y = bad_samples[dataset.target]
    accuracy = metrics.accuracy_score(bad_samples_y, prediction_bad)
    print("Accuracy of Fixed model on BAD samples only:", accuracy)
    result["FIXED accuracy on bad samples"] = accuracy

    # Check diagnosis queality
    if check_diagnosis:
        result["faulty nodes"] = faulty_nodes
        result["# faulty nodes "] = len(faulty_nodes)
        # check how many features fixed
        diagnosis_features = {}
        good_fixed = 0
        for node in diagnosis:
            feature = model.tree_.feature[node]
            feature_name = dataset.features[feature]
            diagnosis_features[feature_name] = diagnosis_features.get(feature_name, 0) +1
            if node in faulty_nodes:
                good_fixed += 1
        result["# total features fixed"] = len(diagnosis_features)
        result["# faulty nodes fixed"] = good_fixed

        # check how many faulty features
        faulty_features = set()
        for node in faulty_nodes:
            feature = model.tree_.feature[node]
            feature_name = dataset.features[feature]
            faulty_features.add(feature_name)
        result["# faulty features"] = len(faulty_features)

        # check how many features fixed out of the faulty features
        fixed = 0
        faulty_feature_nodes_fixed = 0
        for feature in faulty_features:
            if feature in diagnosis_features:
                fixed += 1
                faulty_feature_nodes_fixed += diagnosis_features[feature]
        result["# faulty features fixed"] = fixed
        result["unnecessary features fixed"] = len(diagnosis_features) - fixed
        result["faulty features nodes fixed"] = faulty_feature_nodes_fixed
        result["unnecessary nodes fixed"] = len(diagnosis) - faulty_feature_nodes_fixed

        # check diagnosis quality - WE and #diagnosis until nodes are fixed
        real_diagnosis = set(faulty_nodes)
        already_fixed = set()
        i = 0
        wasted_effort = 0
        while len(real_diagnosis) > 0 and i < len(diagnoses):
            d = diagnoses[i]
            if type(d) == int:
                d = [d]
            for node in d:
                if node not in real_diagnosis:
                    if node not in already_fixed:
                        wasted_effort += 1
                        already_fixed.add(node)
                else:
                    real_diagnosis.remove(node)
            i += 1

        print(f"wasted effort = {wasted_effort}")
        result["wasted effort - nodes"] = wasted_effort
        result["#diagnosis until faulty node"] = i
        result["diagnosis found?"] = 1
        if len(real_diagnosis) > 0: # node was not detected
            result["#diagnosis until faulty node"] = -1
            result["diagnosis found?"] = 0
        result["probability difference"] = probabilities[0] - probabilities[i-1]

        faulty_node = faulty_nodes[0]
        spectra = np.array(spectra)
        error_vector = np.array(error_vector)
        samples_in_node_mask = spectra[:,faulty_node] == 1
        samples_in_node_after_drift = samples_in_node_mask.sum()
        errors_in_node = error_vector[samples_in_node_mask].sum()
        assert samples_in_node_after_drift >= errors_in_node
        result["samples in node after drift"] = samples_in_node_after_drift
        result["# errors in node after drift"] = errors_in_node
        errors_p = errors_in_node / samples_in_node_after_drift if samples_in_node_after_drift > 0 else -1
        result["% errors in node after drift"] = errors_p

    # test all fixes
    if len(faulty_nodes) > 0:  # fix the tree, diagnosis = faulty node
        # train subtree
        model_to_fix = copy.deepcopy(model)
        fixed_model_train_subtree = train_subtree(model_to_fix, faulty_nodes[0], dataset, model_rep)
        if fixed_model_train_subtree == -1:  # no samples in node
            result["TrainSubtree: accuracy fixed model (faulty nodes) - test data"] = -1
        else:
            prediction4 = fixed_model_train_subtree.predict(test_set_x)
            accuracy = metrics.accuracy_score(test_set_y, prediction4)
            print("Accuracy of the Fixed model (based on faulty nodes) on test data:", accuracy)
            result["TrainSubtree: accuracy fixed model (faulty nodes) - test data"] = accuracy

        model_to_fix = copy.deepcopy(model)
        fixed_model_change_threshold_node = fix_nodes_by_type(model_to_fix, faulty_nodes, dataset,
                                                              diff_type="node", tree_rep=model_rep)
        prediction = fixed_model_change_threshold_node.predict(test_set_x)
        accuracy = metrics.accuracy_score(test_set_y, prediction)
        result["NodeThreshold: accuracy fixed model (faulty nodes) - test data"] = accuracy

        model_to_fix = copy.deepcopy(model)
        fixed_model_change_threshold_all = fix_nodes_by_type(model_to_fix, faulty_nodes, dataset)
        prediction = fixed_model_change_threshold_all.predict(test_set_x)
        accuracy = metrics.accuracy_score(test_set_y, prediction)
        result["AllThreshold: accuracy fixed model (faulty nodes) - test data"] = accuracy

    return result

if __name__ == '__main__':
    for data in all_datasets_single_tree[0:1]:
        print(f"#### Experiment of dataset: {data.name} ####")
        run_single_tree_experiment(data)
        print("-----------------------------------------------------------------------------------------")
