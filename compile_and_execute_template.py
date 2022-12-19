import json
import sys
import os
import getopt
import boto3
import jinja2
import yaml
import string
import random
import traceback

from enum import Enum, unique

from botocore.exceptions import ClientError

COMMON_FILE_PATH = 'cf_vars/common.yml'


@unique
class Actions(Enum):
    FILL = 'fill'
    DEPLOY = 'deploy'


def id_generator(size=6, chars=string.ascii_uppercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))


def stack_exists(stack_name: str) -> bool:
    try:
        cf = boto3.client('cloudformation')
        cf.describe_stacks(
            StackName=stack_name
        )

        print(f'{stack_name} stack found.')

        return True
    except ClientError:
        print(f'{stack_name} stack not found.')
        return False


def get_changes(change_set_name: str, stack_name: str) -> None:
    try:
        cf = boto3.client('cloudformation')
        output = cf.describe_change_set(
            ChangeSetName=change_set_name,
            StackName=stack_name
        )

        print(output['Changes'])

    except Exception as e:
        print(f'An error has occurred retrieving change set {change_set_name} changes: {e}')
        sys.exit(2)


def create_change_set(stack_name: str, body: str, parameters: list) -> None:
    try:
        cf = boto3.client('cloudformation')
        waiter = cf.get_waiter('change_set_create_complete')

        random_id = id_generator()

        change_set_name = f'{stack_name}-{random_id}'

        cf.create_change_set(
            StackName=stack_name,
            TemplateBody=body,
            Parameters=parameters,
            ChangeSetName=change_set_name,
            Capabilities=['CAPABILITY_NAMED_IAM']
        )

        waiter.wait(
            ChangeSetName=change_set_name,
            StackName=stack_name,
            WaiterConfig={
                'Delay': 10
            }
        )

        # get_changes(change_set_name, stack_name)

        print(f'Change set {change_set_name} for stack {stack_name} created!')

        return

    except Exception as e:
        print(f'An error has occurred during the creation of the change set: {e}')
        sys.exit(2)


def create_stack(stack_name: str, body: str, parameters: list) -> None:
    try:
        cf = boto3.client('cloudformation')
        waiter = cf.get_waiter('stack_create_complete')

        cf.create_stack(
            StackName=stack_name,
            TemplateBody=body,
            Parameters=parameters,
            Capabilities=['CAPABILITY_NAMED_IAM']
        )

        waiter.wait(
            StackName=stack_name,
            WaiterConfig={
                'Delay': 10
            }
        )

        print(f'Stack {stack_name} created!')

        return

    except Exception as e:
        print(f'An error has occurred during the creation of the stack: {e}')
        sys.exit(2)


def deploy_stack(init: dict, json_parameters: list) -> None:
    try:

        sn = init.get('stackName')
        body = init.get('stackBody')

        print(f"Checking if the {sn} stack exists.")

        if stack_exists(sn):
            print(f'Creating change set for stack: {sn}')

            create_change_set(sn, body, json_parameters)

            return

        print(f'Stack {sn} does not exists, creating it...')

        create_stack(sn, body, json_parameters)

        return

    except Exception as e:
        print(f'An error has occurred during the stack creation: {e}')
        sys.exit(2)


def merge_vars_file(init: dict) -> dict:
    try:
        common_values = yaml.safe_load(open(COMMON_FILE_PATH))

        custom_values = yaml.safe_load(open(init.get('valuesFile')))

        custom_values.update(common_values)

        return custom_values

    except Exception as e:
        print(f'An error has occurred merging the vars files: {e}')
        sys.exit(2)


def fill_json(init: dict) -> list:
    try:
        parameter_file = open(init.get('jsonFile')).read()

        values = merge_vars_file(init)

        print(values)

        output = list(eval(jinja2.Template(parameter_file).render(values)))

        return output

    except Exception as e:
        print(f'An error has occurred filling the json file: {e}')
        sys.exit(2)


def check_file(file: str) -> bool:
    try:
        if not os.path.isfile(file):
            raise Exception(f'File {file} does not exists!')

        return True

    except Exception as e:
        print(f'An error has occurred checking {file}: {e}')
        sys.exit(2)


def save_to_file(name: str, content: list, extension: str) -> None:
    try:
        file_name = f"{name}.{extension}"
        file = open(file_name, 'w')
        file.write(json.dumps(content, sort_keys=True, indent=4))
        file.close()

    except Exception as e:
        print(f'An error occurred during the save of json file: {e}')
        sys.exit(2)


def init_variables(env: str, t: str) -> dict:
    try:
        values_file = f'cf_vars/{env}.yml'

        check_file(values_file)
        check_file(t)

        t_file_name = t.split('/')[-1]

        # the path to yaml wil WITH trailing /
        path = t.replace(t_file_name, '')

        # the template name WITHOUT extension. foo.yaml becomes foo
        clean_name = t_file_name.replace('.yaml', '').replace('.yml', '')

        json_file = f'{path}{clean_name}.json'

        check_file(json_file)

        stack_name = f'ct-{env}-base-{clean_name}-stack'

        stack_body = open(t).read()

        output = {
            'valuesFile': values_file,
            'templateFileName': t_file_name,
            'jsonFile': json_file,
            'stackName': stack_name,
            'stackBody': stack_body
        }

        return output

    except Exception as e:
        print(f'An error has occurred in init_variables: {e}')
        sys.exit(2)


def main(argv) -> None:
    environment = ""
    template = ""
    action = ""
    arg_help = "{0} -e <environment> -t <template> -a <fill|deploy>".format(argv[0])

    try:
        opts, args = getopt.getopt(argv[1:], "he:t:a:", ["help", "environment=",
                                                         "template=", "action="])

        for opt, arg in opts:
            if opt in ("-h", "--help"):
                print(arg_help)
                sys.exit(2)
            elif opt in ("-e", "--environment"):
                environment = arg
            elif opt in ("-t", "--template"):
                template = arg
            elif opt in ("-a", "--action"):
                action = arg

        if not action:
            raise Exception('Action must be defined')

        if action not in [item.value for item in Actions]:
            raise Exception(f'Action {action} not supported, supported actions are: {list(map(str, Actions))}')

        if not environment:
            raise Exception('Environment must be defined')

        if not template:
            raise Exception('Template must be defined')

        init = init_variables(environment, template)

        if action == Actions.DEPLOY.value:
            filled_json = fill_json(init)
            deploy_stack(init, filled_json)

        if action == Actions.FILL.value:
            filled_json = fill_json(init)
            save_to_file(init.get('stackName'), filled_json, 'json')

        return

    except Exception as e:
        print(f'An error has occurred: {e}')
        traceback.print_exc()
        sys.exit(2)


if __name__ == '__main__':
    main(sys.argv)
