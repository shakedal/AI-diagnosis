from sfl.Diagnoser.diagnoserUtils import write_json_planning_file, readPlanningFile
import numpy as np
from Barinel import calculate_diagnoses_and_probabilities_barinel_shaked


THRESHOLD = 0.1
ONLY_POSITIVE = True
MATRIX_FILE_PATH = 'matrix_for_SFL1'
PARENTS = dict()

def build_SFL_matrix(description, components_names, priors, initial_tests, test_details):
    with open(MATRIX_FILE_PATH, 'w') as f:
        f.write('[Description]\n')
        f.write('{}\n'.format(description))

        f.write('[Components names]\n')
        f.write('{}\n'.format(components_names))

        f.write('[Priors]\n')
        f.write('{}\n'.format(priors))

        f.write('[Bugs]\n')  # always empty - irrelevant
        f.write('[]\n')

        f.write('[InitialTests]\n')
        f.write('{}\n'.format(initial_tests))

        f.write('[TestDetails]\n')  # list of tests
        for test in test_details:
            f.write('{}\n'.format(test))

def build_SFL_matrix_SHAP(features, shap_values, prediction, labels, data_set_name):
    number_of_samples = len(prediction)
    initial_tests = list(map(lambda x: f'T{x}', range(number_of_samples)))  # test for each sample

    positive_components = list(map(lambda x: (2*x, f'{features[x]} positive'), range(len(features))))
    negative_components = list(map(lambda x: (2*x+1, f'{features[x]} negative'), range(len(features))))
    components_names = [*positive_components, *negative_components]
    priors = [1/(len(components_names))]*(len(components_names))  # equal prior probability to all components

    conflicts = set()
    all_test_details = list()
    for i in range(number_of_samples):  # i is sample index
        result = 0 if prediction[i] == labels.values[i] else 1  # 1 if there is an error in prediction
        components = list()
        shap = shap_values[int(prediction[i])][i]  # takes shap value for the predicted
        # TODO: calculate components using filters instead of for
        for j in range(len(shap)): # j is feature index
            value = shap[j]
            if ONLY_POSITIVE:
                if value >= THRESHOLD:
                    component_id = 2 * j
                    components.append(component_id)
            elif abs(value) >= THRESHOLD:  # feature appears as a component
                component_id = 2 * j if value > 0 else 2 * j + 1
                components.append(component_id)

        test_detail = f'T{i};{components};{result}'
        all_test_details.append(test_detail)
        if result == 1:  # classification is wrong
            conflicts.add(tuple(components))

    build_SFL_matrix(data_set_name, components_names, priors, initial_tests, all_test_details)
    print("list of conflicts: {}".format(conflicts))

def get_diagnosis():
    ei = readPlanningFile(MATRIX_FILE_PATH)
    ei.diagnose()
    return ei.diagnoses

def get_matrix_entrance(sample_id, samples, node_indicator, conflicts):
    data_x, prediction, labels = samples
    node_index = node_indicator.indices[            # extract the relevant path for sample_id
                 node_indicator.indptr[sample_id]: node_indicator.indptr[sample_id + 1]
                 ].tolist()
    result = 0 if prediction[sample_id] == labels.values[sample_id] else 1  # 1 if there is an error in prediction
    test_detail = f"T{sample_id};{node_index};{result}"

    if result == 1: # classification is wrong
        conflicts.add(tuple(node_index))

    return test_detail, conflicts

def build_SFL_matrix_Nodes(model, samples, data_set_name):
    data_x, prediction, labels = samples
    number_of_samples = len(data_x)
    initial_tests = list(map(lambda x: f'T{x}', range(number_of_samples))) # test for each sample

    number_of_nodes = model.tree_.node_count
    components = list(map(lambda x: (x, f'node{x}'), range(number_of_nodes)))
    priors = [1/number_of_nodes]*number_of_nodes  # equal prior probability to all nodes

    node_indicator = model.decision_path(data_x)  # all paths
    all_test_details = list()
    conflicts = set()
    for sample_id in range(number_of_samples):
        test_detail, conflicts = get_matrix_entrance(sample_id, samples, node_indicator, conflicts)
        all_test_details.append(test_detail)

    build_SFL_matrix(data_set_name, components, priors, initial_tests, all_test_details)
    print("list of conflicts: {}".format(conflicts))

def get_diagnosis_nodes(model, samples, model_rep):
    BAD_SAMPLES = list()
    data_x, prediction, labels = samples
    number_of_samples = len(data_x)
    number_of_nodes = model.tree_.node_count

    # initialize spectra and error vector
    error_vector = np.zeros(number_of_samples)
    spectra = np.zeros((number_of_samples, number_of_nodes))

    # define prior vector
    priors = np.ones(number_of_nodes) * 0.99
    depth = [model_rep[node]["depth"] for node in range(number_of_nodes)]
    max_depth = max(depth)
    # priors = [0.99 ** (max_depth - depth[node]) for node in range(number_of_nodes)]
    # priors = [0.99**(max_depth - depth[node]) if model_rep[node]["left"] != -1 else 0.99**((max_depth - depth[node])*4) for node in range(number_of_nodes)]
    # priors = [
    #     0.01 * (depth[node]+1) if model_rep[node]["left"] != -1 else 0.01 * (depth[node]+1)/4
    #     for node in range(number_of_nodes)]
    # priors = [
    #     0.1 / (max_depth - depth[node] + 1) # if model_rep[node]["left"] != -1 else 0.1 / (4*(max_depth - depth[node] + 1))
    #     for node in range(number_of_nodes)]
    # priors = [
    #     1 - ((max_depth - depth[node] + 1) / (max_depth + 2))
    #     if model_rep[node]["left"] != -1
    #     else (1 - ((max_depth - depth[node] + 1) / (max_depth + 2))) / 4
    #     for node in range(number_of_nodes)]
    priors = np.array(priors)

    node_indicator = model.decision_path(data_x)  # get paths for all samples
    conflicts = set()
    errors = 0
    for sample_id in range(number_of_samples):
        node_index = node_indicator.indices[  # extract the relevant path for sample_id
                     node_indicator.indptr[sample_id]: node_indicator.indptr[sample_id + 1]
                     ].tolist()
        for node_id in node_index:
            # set as a component in test
            spectra[sample_id][node_id] = 1
        if prediction[sample_id] != labels.values[sample_id]:  # test result is "fail"
            error_vector[sample_id] = 1
            errors += 1
            conflicts.add(tuple(node_index))
            BAD_SAMPLES.append(node_id)

    print(f"Conflicts: {conflicts}")
    print(f"Number of misclassified samples: {errors}")
    diagnoses = calculate_diagnoses_and_probabilities_barinel_shaked(spectra, error_vector, priors)
    return diagnoses, BAD_SAMPLES, spectra, error_vector, conflicts
