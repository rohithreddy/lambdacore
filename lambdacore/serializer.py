# Based on the DefaultSerializer class from ask-sdk project
# https://github.com/alexa/alexa-skills-kit-sdk-for-python/blob/8d0b50384cb213d7ee094c7b78512ea80889fadd/ask-sdk-core/ask_sdk_core/serialize.py

#
# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights
# Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS
# OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the
# License.
#

# pylint: disable=no-else-return,too-many-return-statements,no-self-use

import decimal
from datetime import date, datetime
from enum import Enum
import json
import re
import sys
import typing

if typing.TYPE_CHECKING:
    from typing import TypeVar, Dict, List, Tuple, Union, Any
    T = TypeVar('T') # pylint: disable=invalid-name


class SerializationException(Exception):
    """ Exception raised during serialization or deserialization. """



class StandardSerializer:
    PRIMITIVE_TYPES = (int, float, bool, bytes, str)
    NATIVE_TYPES_MAPPING = {
        'int': int,
        'float': float,
        'str': str,
        'bool': bool,
        'date': date,
        'datetime': datetime,
        'object': object,
    }

    def serialize(self, obj):
        # type: (Any) -> Union[Dict[str, Any], List, Tuple, str, None]
        """Builds a serialized object.

        If obj is None, return None.
        If obj is str, int, long, float, bool, return directly.
        If obj is datetime.datetime, datetime.date convert to
        string in iso8601 format.
        If obj is list, serialize each element in the list.
        If obj is dict, return the dict with serialized values.
        If obj is ask sdk model, return the dict with keys resolved
        from model's ``attribute_map`` and values serialized
        based on ``deserialized_types``.

        :param obj: The data to serialize.
        :type obj: object
        :return: The serialized form of data.
        :rtype: Union[Dict[str, Any], List[Any], Tuple[Any], str, None]
        """
        if obj is None:
            return None
        elif isinstance(obj, self.PRIMITIVE_TYPES):
            return obj
        elif isinstance(obj, list):
            return [self.serialize(sub_obj) for sub_obj in obj]
        elif isinstance(obj, tuple):
            return tuple(self.serialize(sub_obj) for sub_obj in obj)
        elif isinstance(obj, (datetime, date)):
            return obj.isoformat()
        elif isinstance(obj, Enum):
            return obj.value
        elif isinstance(obj, decimal.Decimal):
            if obj % 1 == 0:
                return int(obj)
            else:
                return float(obj)

        if isinstance(obj, dict):
            obj_dict = obj
        else:
            # Convert model obj to dict except
            # attributes `deserialized_types`, `attribute_map`
            # and attributes which value is not None.
            # Convert attribute name to json key in
            # model definition for request.
            class_attribute_map = getattr(obj, 'attribute_map', {})
            class_attribute_map.update({k: k for k
                                        in obj.deserialized_types.keys()
                                        if k not in class_attribute_map})

            obj_dict = {
                class_attribute_map[attr]: getattr(obj, attr)
                for attr, _ in obj.deserialized_types.items()
                if getattr(obj, attr) is not None
            }

        return {key: self.serialize(val) for key, val in obj_dict.items()}

    def deserialize(self, payload, obj_type):
        # type: (str, Union[T, str]) -> Any
        """Deserializes payload into ask sdk model object.

        :param payload: data to be deserialized.
        :type payload: str
        :param obj_type: resolved class name for deserialized object
        :type obj_type: Union[str, object]
        :return: deserialized object
        :rtype: object
        :raises: :py:class:`ask_sdk_core.exceptions.SerializationException`
        """
        if payload is None:
            return None

        try:
            payload = json.loads(payload)
        except Exception:
            raise SerializationException(
                "Couldn't parse response body: {}".format(payload))

        return self.__deserialize(payload, obj_type)

    def __deserialize(self, payload, obj_type):
        # type: (str, Union[T, str]) -> Any
        # pylint: disable=too-many-branches
        """Deserializes payload into ask sdk model object.

        :param payload: data to be deserialized.
        :type payload: str
        :param obj_type: resolved class name for deserialized object
        :type obj_type: Union[str, object]
        :return: deserialized object
        :rtype: T
        """
        if payload is None:
            return None

        if isinstance(obj_type, str):
            if obj_type.startswith('list['):
                # Get object type for each item in the list
                # Deserialize each item using the object type.
                sub_obj_types = re.match(r'list\[(.*)\]', obj_type).group(1)
                deserialized_list = []
                if "," in sub_obj_types:
                    # list contains objects of different types
                    for sub_payload, sub_obj_type in zip(
                            payload, sub_obj_types.split(",")):
                        deserialized_list.append(self.__deserialize(
                            sub_payload, sub_obj_type.strip()))
                else:
                    for sub_payload in payload:
                        deserialized_list.append(self.__deserialize(
                            sub_payload, sub_obj_types.strip()))
                return deserialized_list

            if obj_type.startswith('dict('):
                # Get object type for each k,v pair in the dict
                # Deserialize each value using the object type of v.
                sub_obj_type = re.match(
                    r'dict\(([^,]*), (.*)\)', obj_type).group(2)
                return {
                    k: self.__deserialize(v, sub_obj_type)
                    for k, v in payload.items()
                }

            # convert str to class
            if obj_type in self.NATIVE_TYPES_MAPPING:
                obj_type = self.NATIVE_TYPES_MAPPING[obj_type]
            else:
                # deserialize ask sdk models
                obj_type = self.__load_class_from_name(obj_type)

        if obj_type in self.PRIMITIVE_TYPES:
            return self.__deserialize_primitive(payload, obj_type)
        elif obj_type == object:
            return payload
        elif obj_type == date:
            return self.__deserialize_datetime(payload, obj_type)
        elif obj_type == datetime:
            return self.__deserialize_datetime(payload, obj_type)
        else:
            return self.__deserialize_model(payload, obj_type)

    def __load_class_from_name(self, class_name):
        # type: (str) -> str
        try:
            module_class_list = class_name.rsplit(".", 1)
            if len(module_class_list) > 1:
                module_name = module_class_list[0]
                resolved_class_name = module_class_list[1]
                module = __import__(
                    module_name, fromlist=[resolved_class_name])
                resolved_class = getattr(module, resolved_class_name)
            else:
                resolved_class_name = module_class_list[0]
                resolved_class = getattr(
                    sys.modules[__name__], resolved_class_name)
            return resolved_class
        except Exception as e: # pylint: disable=invalid-name
            raise SerializationException(
                "Unable to resolve class {} from installed "
                "modules: {}".format(class_name, str(e)))

    def __deserialize_primitive(self, payload, obj_type):
        # type: (str, Union[T, str]) -> Any
        """Deserialize primitive datatypes.

        :param payload: data to be deserialized
        :type payload: str
        :param obj_type: primitive datatype str
        :type obj_type: object
        :return: deserialized primitive datatype object
        :rtype: object
        :raises SerializationException
        """
        try:
            return obj_type(payload)
        except TypeError:
            return payload
        except ValueError:
            raise SerializationException(
                "Failed to parse {} into '{}' object".format(
                    payload, obj_type.__name__))

    def __deserialize_datetime(self, payload, obj_type):
        # type: (str, Union[T, str]) -> Any
        """Deserialize datetime instance in ISO8601 format to
        date/datetime object.

        :param payload: data to be deserialized in ISO8601 format
        :type payload: str
        :param obj_type: primitive datatype str
        :type obj_type: object
        :return: deserialized primitive datatype object
        :rtype: object
        :raises SerializationException
        """
        try:
            from dateutil.parser import parse
            parsed_datetime = parse(payload)
            if obj_type is date:
                return parsed_datetime.date()
            else:
                return parsed_datetime
        except ImportError:
            return payload
        except ValueError:
            raise SerializationException(
                "Failed to parse {} into '{}' object".format(
                    payload, obj_type.__name__))

    def __deserialize_model(self, payload, obj_type):
        # type: (str, Union[T, str]) -> Any
        """Deserialize instance to model object.

        :param payload: data to be deserialized
        :type payload: str
        :param obj_type: sdk model class
        :type obj_type: object
        :return: deserialized sdk model object
        :rtype: object
        :raises SerializationException
        """
        try:
            if issubclass(obj_type, Enum):
                return obj_type(payload)

            if hasattr(obj_type, 'deserialized_types'):
                if hasattr(obj_type, 'get_real_child_model'):
                    obj_type = self.__get_obj_by_discriminator(
                        payload, obj_type)

                class_deserialized_types = obj_type.deserialized_types
                class_attribute_map = getattr(obj_type, 'attribute_map', {})
                class_attribute_map.update({k: k for k
                                            in obj_type.deserialized_types.keys()
                                            if k not in class_attribute_map})

                deserialized_model = obj_type()
                for class_param_name, payload_param_name in \
                    class_attribute_map.items():
                    if payload_param_name in payload:
                        setattr(
                            deserialized_model,
                            class_param_name,
                            self.__deserialize(
                                payload[payload_param_name],
                                class_deserialized_types[class_param_name]))

                additional_params = [
                    param for param in payload
                    if param not in class_attribute_map.values()]

                for add_param in additional_params:
                    setattr(deserialized_model, add_param, payload[add_param])
                return deserialized_model
            else:
                return payload
        except Exception as e: # pylint: disable=invalid-name
            raise SerializationException(str(e))

    def __get_obj_by_discriminator(self, payload, obj_type):
        # type: (str, Union[T, str]) -> str
        namespaced_class_name = obj_type.get_real_child_model(payload)
        if not namespaced_class_name:
            raise SerializationException(
                "Couldn't resolve object by discriminator type "
                "for {} class".format(obj_type))

        return self.__load_class_from_name(namespaced_class_name)
