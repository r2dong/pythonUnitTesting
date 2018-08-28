"""
this file contains functions to read functions specs,
student files, and write grading output to file
"""

import os
import csv
from os.path import splitext
from shutil import copy
from os.path import basename
from os import makedirs
from Tester import test_func
from Tester import Func
from ast import literal_eval

# constants
NUM_HEADER_ROWS = 2  # #header rows in grade sheet
NUM_PADDING = 5
NUM_META_ROWS = 4  # first n columns to copy from template grade sheet
GRADE_SHEET_FIRST_ROW = 'Student', 'ID', 'SIS Login ID', 'Section'
HAWK_ID_COL = 2  # column in template with hawkIDs
HAWK_ID_EXC_STR = 'something wrong happend when reading your getHawkIDs function\n'
HAWK_ID_NON_EXIST_STR = 'could not find a match for the hawk id you returned in getHawkIDs function\n' + \
                        'please double check you spelled it right\n'
SYNTAX_ERR = 'It appears that your file has a syntax error\n'


def skip_elems(n, iterator):
    """
    skip n elements of an iterator
    islice method appears problematic for no obvious reason
    """
    for i in range(0, n):
        next(iterator)
    return iterator


def get_hawk_ids(grade_sheet_file_name):
    """
    find all valid hawk_ids from a grade sheet
    :param grade_sheet_file_name: path to a grade sheet
    :return: a list of strings, with all hawk ids from the given grade sheet
    """
    with open(grade_sheet_file_name) as file:
        reader = skip_elems(NUM_HEADER_ROWS, csv.reader(file))
        return [row[HAWK_ID_COL] for row in reader]


# noinspection PyShadowingNames
def read_folder(folder_name):
    """
    reads a folder containing submissions of a single section
    :param folder_name: folder to be read
    :return: a Section instance
    """

    # deal with grade sheet
    fnms = os.listdir(folder_name)  # file names
    path = list(filter(lambda fn: splitext(fn)[1] == '.csv', fnms))[0]
    path = os.path.join(folder_name, path)
    section = Section(folder_name, path)
    valid_hawk_ids = get_hawk_ids(path)

    # deal with all student submission files
    stfnms = list(filter(lambda fn: splitext(fn)[1] != '.csv', fnms))
    for fn in stfnms:
        section.add_file(StudentFile(folder_name, fn, valid_hawk_ids))

    return section


def parse_func_specs(fileName):
    """
    parse a func spec file into Function instances
    :param fileName: path of function spec file
    :return: a list of Function instances
    """
    funcs = []
    is_last = False
    with open(fileName) as file:
        reader = csv.reader(file)
        while not is_last:
            next_func, is_last = parse_one_func(reader)
            funcs.append(next_func)
    return funcs


def parse_one_func(reader):
    """
    read one function out of spec file
    :param reader: csv reader on the func spec file
    :return: a single Function instance
    """

    # meta info of function
    is_last = False
    row = next(reader)
    name = row[0]
    try:
        score = row[1]
    except IndexError:
        score = 1

    # all input sets of function
    arg_sets = []
    row = next(reader)
    while len(row) != 0:
        arg_sets.append([literal_eval(arg) for arg in row])
        try:
            row = next(reader)
        except StopIteration:
            is_last = True
            break

    return Func(name, arg_sets, score), is_last


class Section:
    """ instance representing all submissions of a single section """

    def __init__(self, folder_name, grade_sheet_name):
        self.student_files = []
        self.grade_sheet_name = grade_sheet_name
        self.folder_name = folder_name

    def grade_section(self, sol_fname, funcs):
        """
        grade all submissions of this section
        :param sol_fname: path of solution file
        :param funcs: list of Function instances specifying function specs
        """
        for stf in self.student_files:
            for func in funcs:
                test_func(func, stf, sol_fname)

    def add_file(self, file):
        """
        add a new StudentFile instance
        :param: file: a StudnetFile instance
        """
        self.student_files.append(file)

    def write_test_results(self, out_dir):
        """
        write test feedback to all student files in this section
        :param out_dir: destination directory to place the new files
        """
        os.chdir(out_dir)
        for student_file in self.student_files:
            student_file.write_test_results(basename(self.folder_name))

    def __get_total_score(self, hwid):
        full_path = os.path.join(self.folder_name, self.grade_sheet_name)
        with open(full_path) as file:
            reader = csv.reader(file)
            first_row = next(reader)
            score_row = next(reader)
            return score_row[first_row.index(hwid)]

    # get a score using hawk id, or return none if id does not exist
    def __score_by_id(self, hawk_id):
        for stf in self.student_files:
            if hawk_id == stf.hawk_id:
                return stf.calc_total_score()

    def write_grade_sheet(self, out_dir, hwid):
        """ write the grade sheet for this section """

        first_row = GRADE_SHEET_FIRST_ROW + (hwid,)
        total_score = self.__get_total_score(hwid)
        second_row = ['Points Possible'] + [''] * (NUM_META_ROWS - 1) + [str(total_score)]
        tfn = os.path.join(self.folder_name, self.grade_sheet_name)  # grade sheet file name
        ofn = os.path.join(out_dir, basename(self.folder_name), basename(self.grade_sheet_name))  # out file name

        with open(ofn, 'w') as out_file, open(tfn, 'r') as template_file:

            writer = csv.writer(out_file, lineterminator='\n')
            writer.writerow(first_row)
            writer.writerow(second_row)
            tf_reader = skip_elems(NUM_HEADER_ROWS, csv.reader(template_file))

            for row in tf_reader:
                hawk_id = row[HAWK_ID_COL]
                score = self.__score_by_id(hawk_id)
                row = row[:NUM_META_ROWS]
                if score is not None:
                    row += [str(score)]
                writer.writerow(row)


class StudentFile:
    """ represents a single submission from a student """

    def __init__(self, folder_name, file_name, valid_ids):
        self.path = os.path.join(folder_name, file_name)
        self.folder_name = folder_name
        self.full_file_name = file_name
        self.no_ext_file_name = file_name[:-3]
        self.hawk_id_exc_str = None  # exception ocurrs while getting hawk id
        self.hawk_id_err = False  # hawk id does not exist
        self.hawk_id = None
        self.function_test_results = []
        self.__validate_hawk_id(valid_ids)

    def __validate_hawk_id(self, valid_ids):
        # noinspection PyBroadException
        try:  # first check if there is syntax error (if the file loads)
            __import__(self.no_ext_file_name)
        except Exception:
            self.hawk_id_exc_str = SYNTAX_ERR
        if self.hawk_id_exc_str is None:
            # noinspection PyBroadException
            try:
                self.hawk_id = __import__(self.no_ext_file_name).getHawkIDs()[0]
            except Exception:
                self.hawk_id_exc_str = HAWK_ID_EXC_STR

        if self.hawk_id is not None:
            if self.hawk_id not in valid_ids:
                self.hawk_id_err = True

    # append test results as comments at back of file
    def write_test_results(self, out_dir):
        """
        make a copy of the student submission, then write feedbacks as comments to the end
        :param out_dir: output destination of the grade sheet
        """
        string = ''
        if self.hawk_id_exc_str is not None:
            string += self.hawk_id_exc_str
        elif self.hawk_id_err:
            string += HAWK_ID_NON_EXIST_STR
        for func_result in self.function_test_results:
            string += str(func_result) + '\n'
            # TODO simplify output
            for i in range(0, len(func_result.arg_set_test_results)):
                string += 'case: ' + str(i) + ':\n'
                string += str(func_result.arg_set_test_results[i]) + '\n' * 2
            # TODO simplify absolute and relative path with object
        makedirs(out_dir, exist_ok=True)
        old_file_name = os.path.join(self.folder_name, self.full_file_name)
        new_file_name = os.path.join(out_dir, self.full_file_name)
        path = copy(old_file_name, new_file_name)
        with open(path, 'a') as file:
            file.write('\n' * NUM_PADDING)
            file.write((lambda s: '# ' + s.replace("\n", "\n# "))(string))

    def calc_total_score(self):
        """
        calculate the score of this student
        :return: the score
        """
        score = 0
        for result in self.function_test_results:
            score += result.calc_score()
        return score