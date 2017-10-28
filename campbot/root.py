from __future__ import print_function, unicode_literals, division

import requests
from datetime import datetime, timedelta
from dateutil import parser
import pytz
import logging
import time
import re
import difflib

from . import objects

try:
    input = raw_input
except NameError:
    pass


class UserInterrupt(BaseException):
    pass


class BaseBot(object):
    min_delay = timedelta(seconds=1)

    def __init__(self, campbot, api_url, proxies=None):
        self.campbot = campbot
        self.api_url = api_url
        self._session = requests.Session()
        self.proxies = proxies
        self._next_request_datetime = datetime.now()

    @property
    def headers(self):
        return self._session.headers

    def _wait(self):
        to_wait = (self._next_request_datetime - datetime.now()).total_seconds()

        if to_wait > 0:
            time.sleep(to_wait)

        self._next_request_datetime = datetime.now() + self.min_delay

    def get(self, url, **kwargs):
        self._wait()
        logging.debug("GET %s", url)

        res = self._session.get(self.api_url + url,
                                proxies=self.proxies,
                                params=kwargs)

        res.raise_for_status()

        if res.headers['Content-type'].startswith('application/json'):
            return res.json()

        return res.content

    def post(self, url, data):
        self._wait()
        logging.debug("POST %s", url)

        res = self._session.post(self.api_url + url, json=data,
                                 proxies=self.proxies)

        res.raise_for_status()

        if res.headers['Content-type'].startswith('application/json'):
            return res.json()

        return res.content

    def put(self, url, data):
        self._wait()
        logging.debug("POST %s", url)

        res = self._session.put(self.api_url + url, json=data,
                                proxies=self.proxies)

        res.raise_for_status()

        if res.headers['Content-type'].startswith('application/json'):
            return res.json()

        return res.content


class WikiBot(BaseBot):
    def get_route(self, route_id):
        return objects.Route(self.campbot, self.get("/routes/{}".format(route_id)))

    def get_user(self, user_id=None, wiki_name=None, forum_name=None):
        if user_id:
            return objects.WikiUser(self.campbot, self.get("/profiles/{}".format(user_id)))

        name = wiki_name or forum_name

        data = self.get("/search?q={}&t=u&limit=50".format(name))

        prop = "name" if wiki_name else "forum_username"

        for item in data["users"]["documents"]:
            if item[prop] == name:
                return self.get_user(user_id=item["document_id"])

        return None

    def get_contributions(self, **kwargs):

        oldest_date = kwargs.get("oldest_date", None) or datetime.today() + timedelta(days=-1)
        newest_date = kwargs.get("newest_date", None) or datetime.now()
        user_id = kwargs.get("user_id", None)
        user_filter = "&u={}".format(user_id) if user_id else ""

        oldest_date = oldest_date.replace(tzinfo=pytz.UTC)
        newest_date = newest_date.replace(tzinfo=pytz.UTC)

        d = self.get("/documents/changes?limit=50" + user_filter)
        while True:
            for item in d["feed"]:
                written_at = parser.parse(item["written_at"])
                if oldest_date > written_at:
                    raise StopIteration

                if newest_date > written_at:
                    yield item

            if "pagination_token" not in d:
                break

            pagination_token = d["pagination_token"]
            d = self.get("/documents/changes?limit=50&token=" + pagination_token + user_filter)


class ForumBot(BaseBot):
    def get_group_members(self, group_name):
        result = []

        expected_len = 1
        while len(result) < expected_len:
            data = self.get("/groups/{}/members.json?limit=50&offset={}".format(group_name, len(result)))
            expected_len = data["meta"]["total"]
            result += data["members"]

        return [objects.ForumUser(self.campbot, user) for user in result]

    def get_topic(self, topic_id=None, url=None):
        if url:
            url = url.replace(self.api_url, "").split("?")[0].split("/")
            assert url[1] == 't'
            topic_id = int(url[3])

        return self.get("/t/{}.json".format(topic_id))

    def get_post(self, topic_id=None, post_number=None, url=None):
        if url:
            url = url.replace(self.api_url, "").split("?")[0].split("/")
            assert url[1] == 't'
            topic_id = url[3]
            post_number = int(url[4]) if len(url) >= 5 else 1

        topic = self.get_topic(topic_id)
        post_id = topic["post_stream"]["stream"][post_number - 1]

        return objects.Post(self.campbot, self.get("/posts/{}.json".format(post_id)))

    def get_participants(self, url):
        topic = self.get_topic(url=url)
        return topic["details"]["participants"]


class CampBot(object):
    def __init__(self, proxies=None):
        self.wiki = WikiBot(self, "https://api.camptocamp.org", proxies=proxies)
        self.forum = ForumBot(self, "https://forum.camptocamp.org", proxies=proxies)

        self.forum.headers['X-Requested-With'] = "XMLHttpRequest"
        self.forum.headers['Host'] = "forum.camptocamp.org"

    def login(self, login, password):
        res = self.wiki.post("/users/login", {"username": login, "password": password, "discourse": True})
        token = res["token"]
        self.wiki.headers["Authorization"] = 'JWT token="{}"'.format(token)
        self.forum.get(res["redirect_internal"].replace(self.forum.api_url, ""))

    def check_voters(self, url, allowed_groups=()):

        allowed_members = []
        for group in allowed_groups:
            allowed_members += self.forum.get_group_members(group)

        allowed_members = {u.username: u for u in allowed_members}

        post = self.forum.get_post(url=url)
        for poll_name in post.polls:
            for option in post.polls[poll_name].options:
                print(poll_name, option.html, "has", option.votes, "voters : ")
                for voter in option.get_voters(post.id, poll_name):
                    if voter.username in allowed_members:
                        print("    ", voter.username, "is allowed")
                    else:
                        contributor = voter.get_wiki_user()
                        last_contribution = contributor.get_last_contribution()
                        if not last_contribution:
                            print("    ", voter.username, "has no contribution")
                        else:
                            print("    ", voter.username, last_contribution["written_at"])

            print()

    def fix_markdown(self, processor, route_ids):
        for route_id in route_ids:
            route = self.wiki.get_route(route_id)
            updated = route.fix_markdown(processor)

            if updated:
                if input("Save https://www.camptocamp.org/routes/{} y/[n]?".format(route_id)) == "y":
                    print("Saving...")
                    # route.save("Replace BBcode by Markdown")

                print()
            else:
                print("Nothing found on https://www.camptocamp.org/routes/{}".format(route_id))


class MarkdownProcessor(object):
    def __call__(self, markdown, field, locale, wiki_object):
        raise NotImplementedError()


class Converter(object):
    def __init__(self, pattern, repl, flags):
        self.re = re.compile(pattern=pattern, flags=flags)
        self.repl = repl
        self.flags = flags

    def __call__(self, text):
        return self.re.sub(repl=self.repl, string=text)


class BBCodeRemover(MarkdownProcessor):
    def __init__(self):
        def get_typo_cleaner(bbcode_tag, markdown_tag):
            converters = [

                Converter(pattern=r'\n *\[' + bbcode_tag + r'\] *',
                          repl=r"\n[" + bbcode_tag + r"]",
                          flags=re.IGNORECASE),

                Converter(pattern=r'\[' + bbcode_tag + r'\] +',
                          repl=r" [" + bbcode_tag + r"]",
                          flags=re.IGNORECASE),

                Converter(pattern=r' +\[/' + bbcode_tag + r'\]',
                          repl=r"[" + bbcode_tag + r"] ",
                          flags=re.IGNORECASE),

                Converter(pattern=r'\[' + bbcode_tag + r'\]([^\n\r\*\`]*?)\[/' + bbcode_tag + '\]',
                          repl=markdown_tag + r"\1" + markdown_tag,
                          flags=re.IGNORECASE),
            ]

            def result(markdown):
                for converter in converters:
                    markdown = converter(markdown)

                return markdown

            return result

        self.cleaners = [
            get_typo_cleaner("b", "**"),
            get_typo_cleaner("i", "*"),
            get_typo_cleaner("c", "`"),
            # get_typo_cleaner("u", "__"),
        ]

    def __call__(self, markdown, field, locale, wiki_object):
        result = markdown
        for cleaner in self.cleaners:
            result = cleaner(result)

        d = difflib.Differ()
        diff = d.compare(markdown.split("\n"), result.split("\n"))
        for dd in diff:
            if dd[0] != " ":
                print(dd)

        return result